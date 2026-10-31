"""Подсистема MCP-клиента: контракты, транспорты и пул сессий."""
from .contracts import (
    McpServerConfig,
    McpServerSummary,
    McpService,
    McpToolDescriptor,
)
from .client_factory import mcp_available, open_session
from .session_pool import McpSessionPool

__all__ = [
    "McpServerConfig",
    "McpServerSummary",
    "McpService",
    "McpToolDescriptor",
    "mcp_available",
    "open_session",
    "McpSessionPool",
]
