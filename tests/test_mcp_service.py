"""Тесты MCP-клиента: парсинг пресетов, интеграция с ToolManager.

Интеграция с реальным MCP-SDK и серверами не проверяется здесь (требует
установленного `mcp` и живого сервера); вместо этого проверяются контракты
сервиса и мост через ToolManager с моком.
"""
from __future__ import annotations

from typing import Any, Dict, List

from core.services import services
from services.mcp.contracts import McpService, McpServerSummary
from services.mcp_service import DefaultMcpService, parse_server_config

from managers.tools.tool_manager import ToolManager


class FakeMcpService(McpService):
    def __init__(self, tools: List[Dict[str, Any]]) -> None:
        self._tools = tools
        self.calls: List[tuple] = []

    def servers(self) -> List[McpServerSummary]:
        return []

    def tools_schema(self) -> List[Dict[str, Any]]:
        return list(self._tools)

    def refresh_tools(self) -> None:
        pass

    def call_tool(self, tool_name: str, arguments: Dict[str, Any], *, timeout: float = 60.0) -> str:
        self.calls.append((tool_name, arguments))
        return f"result:{tool_name}"


# ---------------------------------------------------------------------------
# parse_server_config
# ---------------------------------------------------------------------------

def test_parse_server_config_full():
    cfg = parse_server_config(
        {
            "server_id": "fs",
            "name": "Filesystem",
            "transport": "stdio",
            "enabled": True,
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem"],
            "env": {"FOO": "bar"},
            "timeout": 30,
        }
    )
    assert cfg is not None
    assert cfg.server_id == "fs"
    assert cfg.name == "Filesystem"
    assert cfg.transport == "stdio"
    assert cfg.enabled is True
    assert cfg.command == "npx"
    assert cfg.args == ("-y", "@modelcontextprotocol/server-filesystem")
    assert cfg.env == {"FOO": "bar"}
    assert cfg.timeout == 30.0


def test_parse_server_config_http_defaults():
    cfg = parse_server_config({"server_id": "srv", "transport": "http", "url": "http://localhost:8000"})
    assert cfg is not None
    assert cfg.transport == "http"
    assert cfg.enabled is False
    assert cfg.url == "http://localhost:8000"
    assert cfg.timeout == 60.0


def test_parse_server_config_invalid():
    assert parse_server_config(None) is None
    assert parse_server_config("nope") is None
    assert parse_server_config({"name": "no-id"}) is None


# ---------------------------------------------------------------------------
# ToolManager integration
# ---------------------------------------------------------------------------

def _register_fake_mcp(tools):
    fake = FakeMcpService(tools)
    services().register(McpService, fake, replace=True)
    return fake


def test_tool_manager_includes_mcp_schema():
    fake = _register_fake_mcp(
        [
            {"name": "mcp_fs_read", "description": "Read a file", "parameters": {"type": "object"}},
        ]
    )
    try:
        tm = ToolManager()
        schema = tm.json_schema()
        names = {item["name"] for item in schema}
        assert "mcp_fs_read" in names
        # Локальные инструменты тоже на месте
        assert "calculator" in names
    finally:
        services().unregister(McpService, owner=None)


def test_tool_manager_run_falls_back_to_mcp():
    fake = _register_fake_mcp([{"name": "mcp_ping", "description": "", "parameters": {}}])
    try:
        tm = ToolManager()
        result = tm.run("mcp_ping", {"x": 1})
        assert result == "result:mcp_ping"
        assert ("mcp_ping", {"x": 1}) in fake.calls
    finally:
        services().unregister(McpService, owner=None)


def test_tool_manager_run_unknown_without_mcp():
    # Без зарегистрированного McpService — понятная ошибка.
    services().unregister(McpService, owner=None)
    tm = ToolManager()
    assert "[Tool-Error]" in tm.run("does_not_exist", {})


# ---------------------------------------------------------------------------
# DefaultMcpService parsing of settings
# ---------------------------------------------------------------------------

class _FakeSettings:
    def __init__(self, servers: List[dict]) -> None:
        self._servers = servers

    def get(self, key, default=None):
        if key == "MCP_SERVERS":
            return self._servers
        return default


class _FakeLoopService:
    def is_running(self):
        return False

    def run(self, coro):
        raise RuntimeError("no loop")


def test_builtin_server_autoregistered(monkeypatch):
    from pathlib import Path

    fake_path = Path("C:/fake/mcp_system_interaction_server.py")
    monkeypatch.setattr(
        DefaultMcpService, "_find_builtin_server", staticmethod(lambda: fake_path)
    )
    settings = _FakeSettings([])
    service = DefaultMcpService(settings, _FakeLoopService())
    servers = service.servers()
    ids = [server.server_id for server in servers]
    assert "system_interaction" in ids
    assert any(server.enabled for server in servers if server.server_id == "system_interaction")


def test_default_service_reads_settings(monkeypatch):
    # Авто-обнаружение встроенного сервера отключаем для чистоты теста.
    monkeypatch.setattr(DefaultMcpService, "_find_builtin_server", staticmethod(lambda: None))
    settings = _FakeSettings(
        [
            {"server_id": "a", "transport": "stdio", "enabled": True},
            {"server_id": "b", "transport": "http", "enabled": False},
        ]
    )
    service = DefaultMcpService(settings, _FakeLoopService())
    servers = service.servers()
    assert len(servers) == 2
    assert servers[0].server_id == "a"
    assert servers[1].enabled is False
    # loop не запущен -> схема пустая, без падений
    assert service.tools_schema() == []
    assert "MCP-Error" in service.call_tool("x", {})
