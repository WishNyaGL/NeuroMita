"""Фабрика MCP-сессий: stdio и streamable HTTP.

Используется официальный SDK Model Context Protocol (`mcp`, python-sdk).
Если SDK не установлен, модуль корректно деградирует: `mcp_available()`
вернёт False, а открытие сессии поднимет понятную ошибку.
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator


def _ensure_pywin32_on_path() -> None:
    """Добавить пути pywin32 (win32, win32/lib, pythonwin) в sys.path.

    Встроенный Python игры не обрабатывает pywin32.pth, поэтому модули
    pywin32 (в т.ч. pywintypes) не видны. Добавляем их вручную из
    site-packages перед импортом mcp.
    """
    try:
        for base in list(sys.path):
            if str(base).endswith("site-packages"):
                for rel in ("win32", "win32\\lib", "pythonwin"):
                    path = os.path.join(base, rel)
                    if os.path.isdir(path) and path not in sys.path:
                        sys.path.insert(0, path)
    except Exception:  # noqa: BLE001
        pass


_ensure_pywin32_on_path()

try:  # pragma: no cover - зависит от окружения
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    # В mcp 1.x транспорта HTTP называется streamablehttp_client, в 2.x —
    # streamable_http_client. Поддерживаем оба имени.
    try:
        from mcp.client.streamable_http import streamable_http_client as _HTTP_STREAM_CLIENT
    except ImportError:  # mcp 1.x
        from mcp.client.streamable_http import streamablehttp_client as _HTTP_STREAM_CLIENT

    _MCP_AVAILABLE = True
except Exception:  # SDK отсутствует — деградируем
    _MCP_AVAILABLE = False
    ClientSession = None  # type: ignore[assignment]
    StdioServerParameters = None  # type: ignore[assignment]
    stdio_client = None  # type: ignore[assignment]
    _HTTP_STREAM_CLIENT = None  # type: ignore[assignment]

from .contracts import McpServerConfig


def mcp_available() -> bool:
    """Доступен ли официальный MCP-SDK."""
    return _MCP_AVAILABLE


@asynccontextmanager
async def open_session(config: McpServerConfig) -> AsyncIterator["ClientSession"]:
    """Открыть и инициализировать сессию, затем держать её открытой.

    Это корректный async-контекст-менеджер (не generator): внутри
    `async with open_session(config) as session:` транспорт и сессия
    открываются, а после выхода — закрываются.
    """
    if not _MCP_AVAILABLE:
        raise RuntimeError(
            "MCP SDK is not installed; add 'mcp' to dependencies to enable MCP servers"
        )

    if config.transport in ("http", "streamable_http"):
        if not config.url:
            raise ValueError(
                f"[MCP] server '{config.name}': missing url for HTTP transport"
            )
        async with _HTTP_STREAM_CLIENT(
            config.url, headers=config.headers or None
        ) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    else:
        parameters = StdioServerParameters(
            command=config.command,
            args=list(config.args),
            env=dict(config.env) if config.env else None,
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
