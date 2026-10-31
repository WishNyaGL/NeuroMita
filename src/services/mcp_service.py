"""Реализация McpService: владеет пресетами серверов и пулом сессий.

Приложение запускает asyncio-loop в отдельном потоке (плаController). Вызовы
LLM-генерации живут в своих потоках и синхронны, поэтому здесь есть мост
`_sync()`: он подкидывает корутину в живой loop через LoopService.run() и
ждёт будущее.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from main_logger import logger

from core.app_paths import base_dir

from .mcp.contracts import (
    McpServerConfig,
    McpServerSummary,
    McpService,
    McpToolDescriptor,
)
from .mcp.session_pool import McpSessionPool

DEFAULT_MCP_TIMEOUT = 60.0
BUILTIN_SERVER_ID = "system_interaction"
BUILTIN_SERVER_FILENAME = "mcp_system_interaction_server.py"


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_server_config(raw: Any) -> Optional[McpServerConfig]:
    """Парсинг одного пресета сервера из settings.json (толерантно к типам)."""
    if not isinstance(raw, dict):
        return None
    server_id = str(raw.get("server_id") or raw.get("id") or "").strip()
    if not server_id:
        return None
    name = str(raw.get("name") or server_id or "MCP server").strip()
    return McpServerConfig(
        server_id=server_id,
        name=name,
        transport=str(raw.get("transport") or "stdio").strip().lower(),
        enabled=_coerce_bool(raw.get("enabled"), False),
        command=str(raw.get("command") or "").strip(),
        args=tuple(str(arg) for arg in (raw.get("args") or [])),
        env=dict(raw.get("env") or {}),
        url=str(raw.get("url") or "").strip(),
        headers=dict(raw.get("headers") or {}),
        timeout=float(raw.get("timeout") or DEFAULT_MCP_TIMEOUT),
    )


class DefaultMcpService(McpService):
    def __init__(self, settings: Any, loop_service: Any) -> None:
        self._settings = settings
        self._loop = loop_service
        self._pool = McpSessionPool()

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _find_builtin_server() -> Optional[Path]:
        """Найти встроенный сервер: в корне игры или в scripts/ (dev-сборка)."""
        candidates = (
            base_dir() / BUILTIN_SERVER_FILENAME,
            base_dir() / "scripts" / BUILTIN_SERVER_FILENAME,
        )
        for path in candidates:
            if path.is_file():
                return path
        return None

    def _ensure_builtin_server(self) -> List[McpServerConfig]:
        """Авто-регистрация встроенного сервера, если его ещё нет в настройках."""
        raw_list = list(self._settings.get("MCP_SERVERS", []) or [])
        has_builtin = any(
            isinstance(entry, dict)
            and str(entry.get("server_id")) == BUILTIN_SERVER_ID
            for entry in raw_list
        )
        server_path = self._find_builtin_server()
        if not has_builtin and server_path is not None:
            entry: Dict[str, Any] = {
                "server_id": BUILTIN_SERVER_ID,
                "name": "System Interaction",
                "transport": "stdio",
                "enabled": True,
                "command": sys.executable,
                "args": [str(server_path)],
                "env": {},
                "url": "",
                "headers": {},
                "timeout": DEFAULT_MCP_TIMEOUT,
            }
            raw_list.append(entry)
            try:
                setter = getattr(self._settings, "set", None)
                if callable(setter):
                    setter("MCP_SERVERS", raw_list)
                saver = getattr(self._settings, "save_settings", None)
                if callable(saver):
                    saver()
            except Exception:  # noqa: BLE001
                pass
            logger.info("[MCP] built-in server registered at %s", server_path)
        configs: List[McpServerConfig] = []
        for raw in raw_list:
            parsed = parse_server_config(raw)
            if parsed is not None:
                configs.append(parsed)
        return configs

    def _configs(self) -> List[McpServerConfig]:
        configs = self._ensure_builtin_server()
        self._pool.set_servers(configs)
        return configs

    def _run_in_loop(self, coro_factory: Any, timeout: float) -> Any:
        """Запустить корутину в живом loop и дождаться результата.

        Если loop недоступен (GUI-only / остановлен), корутина не создаётся —
        возвращается None без предупреждений о не-awaited coroutine.
        """
        if not self._loop.is_running():
            logger.warning("[MCP] asyncio loop is not running; cannot schedule MCP call")
            return None
        try:
            coro = coro_factory()
            future = self._loop.run(coro)
        except Exception as exc:  # noqa: BLE001
            logger.error("[MCP] failed to schedule coroutine: %s", exc, exc_info=True)
            return None
        try:
            return future.result(timeout=max(1.0, float(timeout)))
        except Exception as exc:  # noqa: BLE001
            logger.error("[MCP] sync call failed: %s", exc, exc_info=True)
            return None

    # ----------------------------------------------------------- McpService

    def servers(self) -> List[McpServerSummary]:
        summaries: List[McpServerSummary] = []
        for cfg in self._configs():
            summaries.append(
                McpServerSummary(
                    server_id=cfg.server_id,
                    name=cfg.name,
                    transport=cfg.transport,
                    enabled=cfg.enabled,
                )
            )
        return summaries

    def tools_schema(self) -> List[Dict[str, Any]]:
        self._configs()  # синхронизировать пул с текущими настройками
        cached = self._pool.cached_tools()
        if cached:
            return [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                }
                for tool in cached
            ]
        descriptors = self._run_in_loop(lambda: self._pool.list_tools(), timeout=20.0)
        if not descriptors:
            logger.warning(
                "[MCP] tools_schema returned empty (loop unavailable or server errors)"
            )
            return []
        logger.info("[MCP] tools_schema resolved %d tool(s)", len(descriptors))
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            }
            for tool in descriptors
        ]

    def refresh_tools(self) -> None:
        self._configs()
        result = self._run_in_loop(
            lambda: self._pool.list_tools(refresh=True), timeout=30.0
        )
        if not result:
            logger.warning("[MCP] refresh_tools produced no tools")
        else:
            logger.info("[MCP] refresh_tools resolved %d tool(s)", len(result))

    def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        timeout: float = 60.0,
    ) -> str:
        self._configs()
        result = self._run_in_loop(
            lambda: self._pool.call_tool(tool_name, arguments, timeout=timeout),
            timeout=timeout + 10.0,
        )
        if result is None:
            return f"[MCP-Error] call to tool '{tool_name}' timed out or failed"
        return result

    def close(self) -> None:
        try:
            self._run_in_loop(lambda: self._pool.aclose(), timeout=5.0)
        except Exception:  # noqa: BLE001
            pass
