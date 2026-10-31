"""Тесты персистентного пула MCP-сессий.

Без реального MCP-SDK/сервера: подменяем `open_session` фейковым контекст-
менеджером и проверяем, что живое соединение открывается один раз и
переиспользуется между вызовами, а после закрытия переподключается.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, Dict, List

import services.mcp.session_pool as session_pool_mod
from services.mcp.contracts import McpServerConfig
from services.mcp.session_pool import McpSessionPool


class _Counter:
    def __init__(self) -> None:
        self.total = 0
        self.live = 0


class _FakeSession:
    def __init__(self, counter: _Counter) -> None:
        self.counter = counter

    async def initialize(self) -> None:
        pass

    async def list_tools(self):
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="t1", description="d", inputSchema={"type": "object"}
                )
            ]
        )

    async def call_tool(self, name: str, arguments: dict):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=f"ok:{name}")])


class _FakeOpenSession:
    def __init__(self, config, counter: _Counter) -> None:
        self._config = config
        self._counter = counter
        self.session = _FakeSession(counter)

    async def __aenter__(self):
        self._counter.total += 1
        self._counter.live += 1
        await self.session.initialize()
        return self.session

    async def __aexit__(self, *exc):
        self._counter.live -= 1
        return False


def _config(enabled: bool = True) -> McpServerConfig:
    return McpServerConfig(
        server_id="srv",
        name="Srv",
        transport="stdio",
        enabled=enabled,
        command="fake",
        args=(),
    )


async def _run(coro):
    return await asyncio.wait_for(coro, timeout=10.0)


def test_pool_reuses_live_connection() -> None:
    counter = _Counter()
    original = session_pool_mod.open_session

    def fake_open(config):
        return _FakeOpenSession(config, counter)

    session_pool_mod.open_session = fake_open
    try:

        async def scenario():
            pool = McpSessionPool()
            pool.set_servers([_config()])
            try:
                first = await _run(pool.call_tool("t1", {}, timeout=5.0))
                second = await _run(pool.call_tool("t1", {}, timeout=5.0))
                return first, second
            finally:
                await _run(pool.aclose())

        first, second = asyncio.run(scenario())
        assert first == "ok:t1"
        assert second == "ok:t1"
        # Переиспользуется ОДНО живое соединение, а не два.
        assert counter.total == 1
    finally:
        session_pool_mod.open_session = original


def test_pool_reconnects_after_close() -> None:
    counter = _Counter()
    original = session_pool_mod.open_session

    def fake_open(config):
        return _FakeOpenSession(config, counter)

    session_pool_mod.open_session = fake_open
    try:

        async def scenario():
            pool = McpSessionPool()
            pool.set_servers([_config()])
            try:
                await _run(pool.call_tool("t1", {}, timeout=5.0))
                # Полностью закрываем пул — соединение умирает.
                await _run(pool.aclose())
                await _run(pool.call_tool("t1", {}, timeout=5.0))
            finally:
                await _run(pool.aclose())

        asyncio.run(scenario())
        # После закрытия соединение пересоздаётся -> итого два открытия.
        assert counter.total == 2
    finally:
        session_pool_mod.open_session = original
