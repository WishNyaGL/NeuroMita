"""Пул открытых MCP-сессий.

Для каждого включённого сервера держится одно живое соединение (открытая и
инициализированная ClientSession), которое переиспользуется между вызовами.
Соединение поднимается лениво при первом обращении и живёт, пока сервер
включён; при обрыве следующий вызов автоматически переподключается.

Все операции пула выполняются внутри asyncio-loop приложения (см.
DefaultMcpService._run_in_loop), поэтому asyncio-примитивы (Event/Lock/task)
создаются и используются в одном loop.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from main_logger import logger

from .client_factory import open_session
from .contracts import McpServerConfig, McpToolDescriptor

_DEFAULT_CONNECT_TIMEOUT = 30.0


class _McpConnection:
    """Одно живое соединение с сервером, удерживаемое фоновой задачей."""

    def __init__(self, server_id: str, config: McpServerConfig) -> None:
        self.server_id = server_id
        self._config = config
        self._task: Optional[asyncio.Task] = None
        self._session: Any = None
        self._ready: Optional[asyncio.Event] = None
        self._started = asyncio.Event()
        self._create_lock = asyncio.Lock()
        self._call_lock = asyncio.Lock()
        self.last_error = ""

    # ---------------------------------------------------------- lifecycle

    async def _hold(self) -> None:
        """Фоновая задача: держит сессию открытой, пока жива."""
        ready = asyncio.Event()
        self._ready = ready
        self._started.set()
        try:
            async with open_session(self._config) as session:
                self._session = session
                self.last_error = ""
                ready.set()
                while True:
                    await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc) or type(exc).__name__
            self._session = None
            logger.error(
                "[MCP] connection '%s' died: %s", self.server_id, exc, exc_info=True
            )
            ready.set()

    async def ensure_ready(self) -> Any:
        """Гарантировать живое соединение; вернуть сессию (или None)."""
        async with self._create_lock:
            if self._task is None or self._task.done():
                self._started.clear()
                self._task = asyncio.create_task(self._hold())
            await self._started.wait()
            ready = self._ready
        try:
            await asyncio.wait_for(ready.wait(), timeout=_DEFAULT_CONNECT_TIMEOUT)
        except asyncio.TimeoutError:
            self.last_error = f"connection to '{self._config.name}' timed out"
            self._session = None
            return None
        return self._session

    async def call(
        self, tool_name: str, arguments: Dict[str, Any], *, timeout: float
    ) -> Any:
        session = await self.ensure_ready()
        if session is None:
            raise RuntimeError(
                self.last_error or f"connection to '{self._config.name}' unavailable"
            )
        async with self._call_lock:
            return await asyncio.wait_for(
                session.call_tool(tool_name, arguments or {}),
                timeout=timeout,
            )

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._task = None
        self._session = None
        self._ready = None


class McpSessionPool:
    def __init__(self) -> None:
        self._requested_configs: Dict[str, McpServerConfig] = {}
        self._connections: Dict[str, _McpConnection] = {}
        self._cached_tools: Optional[List[McpToolDescriptor]] = None
        self._tool_owner: Dict[str, str] = {}

    # ---------------------------------------------------------------- setup

    def set_servers(self, configs: List[McpServerConfig]) -> None:
        self._requested_configs = {c.server_id: c for c in configs}
        self.invalidate()

    def invalidate(self) -> None:
        self._cached_tools = None
        self._tool_owner.clear()

    async def _prune(self) -> None:
        """Закрыть соединения удалённых или изменённых серверов."""
        wanted = {sid: cfg for sid, cfg in self._requested_configs.items()}
        for sid in list(self._connections):
            conn = self._connections.get(sid)
            if conn is None:
                continue
            config = wanted.get(sid)
            if config is None or conn._config != config:
                self._connections.pop(sid, None)
                await conn.aclose()

    async def _get_connection(self, server_id: str) -> Optional[_McpConnection]:
        await self._prune()
        config = self._requested_configs.get(server_id)
        if config is None:
            return None
        conn = self._connections.get(server_id)
        if conn is None:
            conn = _McpConnection(server_id, config)
            self._connections[server_id] = conn
        return conn

    # ------------------------------------------------------------ discovery

    async def list_tools(self, *, refresh: bool = False) -> List[McpToolDescriptor]:
        if self._cached_tools is not None and not refresh:
            return self._cached_tools

        result: List[McpToolDescriptor] = []
        for server_id, config in self._requested_configs.items():
            if not config.enabled:
                continue
            conn = await self._get_connection(server_id)
            if conn is None:
                continue
            try:
                session = await conn.ensure_ready()
                if session is None:
                    logger.warning(
                        "[MCP] '%s' (%s): %s",
                        config.name,
                        server_id,
                        conn.last_error or "connection unavailable",
                    )
                    continue
                listing = await session.list_tools()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[MCP] Failed to list tools from '%s' (%s): %s",
                    config.name,
                    server_id,
                    exc,
                    exc_info=True,
                )
                continue
            for tool in listing.tools:
                result.append(
                    McpToolDescriptor(
                        server_id=server_id,
                        name=tool.name,
                        description=getattr(tool, "description", "") or "",
                        input_schema=dict(getattr(tool, "input_schema", None) or {}),
                    )
                )

        self._cached_tools = result
        self._tool_owner = {tool.name: tool.server_id for tool in result}
        return result

    def cached_tools(self) -> List[McpToolDescriptor]:
        return list(self._cached_tools or [])

    # ---------------------------------------------------------- invocation

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        timeout: float = 60.0,
    ) -> str:
        if self._cached_tools is None:
            await self.list_tools()

        server_id = self._tool_owner.get(tool_name)
        if not server_id:
            return f"[MCP-Error] no configured server provides tool '{tool_name}'"
        conn = await self._get_connection(server_id)
        if conn is None:
            return f"[MCP-Error] server '{server_id}' is not configured"

        try:
            outcome = await conn.call(tool_name, arguments or {}, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[MCP-Error] tool '%s' on '%s' failed: %s",
                tool_name,
                server_id,
                exc,
            )
            return f"[MCP-Error] {tool_name}: {exc}"

        parts: List[str] = []
        for block in (outcome.content or []):
            if getattr(block, "type", "") == "text":
                text = getattr(block, "text", "")
                if text:
                    parts.append(text)
            else:
                rendered = str(block)
                if rendered:
                    parts.append(rendered)
        return "\n".join(parts) if parts else "(MCP tool returned an empty result)"

    # ----------------------------------------------------------- shutdown

    async def aclose(self) -> None:
        for sid in list(self._connections):
            conn = self._connections.pop(sid, None)
            if conn is not None:
                await conn.aclose()
        self.invalidate()
