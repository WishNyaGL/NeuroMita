"""Контракты и типы данных MCP-подсистемы.

Здесь только абстракции и dataclasses: ни один тип не тянет MCP-SDK или
другие тяжёлые зависимости. Реализации живут рядом (session_pool,
client_factory) и в services/mcp_service.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class McpServerConfig:
    """Пресет MCP-сервера (источник правды — settings.json).

    transport:
      - "stdio"            — локальный сервер через подпроцесс (команда/аргументы)
      - "http"/"streamable_http" — удалённый сервер по streamable HTTP
    """

    server_id: str
    name: str
    transport: str = "stdio"
    enabled: bool = False
    command: str = ""
    args: tuple[str, ...] = ()
    env: Dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    timeout: float = 60.0


@dataclass(frozen=True)
class McpToolDescriptor:
    """Один инструмент, предоставленный конкретным MCP-сервером."""

    server_id: str
    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class McpServerSummary:
    """Метаданные настроенного сервера (для UI/логов)."""

    server_id: str
    name: str
    transport: str
    enabled: bool
    connected: bool = False
    error: str = ""
    tool_count: int = 0


class McpService(ABC):
    """Клиентский мост к MCP-серверам.

    Приложение выступает MCP-клиентом: оно подключается к внешним серверам
    (stdio / streamable HTTP), читает их инструменты и делегирует им вызовы.
    """

    @abstractmethod
    def servers(self) -> List[McpServerSummary]:
        """Метаданные всех настроенных серверов."""

    @abstractmethod
    def tools_schema(self) -> List[Dict[str, Any]]:
        """OpenAI-совместимая схема всех включённых MCP-инструментов.

        Каждый элемент: {"name", "description", "parameters"} (JSON Schema).
        Список кэшируется и обновляется лениво.
        """

    @abstractmethod
    def refresh_tools(self) -> None:
        """Принудительно перечитать инструменты серверов (после правки настроек)."""

    @abstractmethod
    def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        timeout: float = 60.0,
    ) -> str:
        """Синхронно выполнить инструмент; возвращает текстовый результат."""
