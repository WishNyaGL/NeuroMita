"""Раздел настроек MCP-серверов.

Позволяет добавлять/редактировать/удалять, включать и выключать MCP-серверы
(stdio или streamable HTTP), а также принудительно обновлять список
инструментов из подключённых серверов.

Данные хранятся в настройках под ключом `MCP_SERVERS` (список словарей).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.settings_section_header import create_settings_header
from ui.settings.settings_access import set_setting, settings_store
from utils import _

# ---------------------------------------------------------------------------
# Сервис
# ---------------------------------------------------------------------------


def _mcp_service():
    try:
        from core.services import services
        from services.mcp.contracts import McpService

        return services().get_optional(McpService)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Доступ к настройкам
# ---------------------------------------------------------------------------


def _read_servers(gui) -> List[dict]:
    store = settings_store(gui)
    if store is None:
        return []
    getter = getattr(store, "get", None)
    if callable(getter):
        raw = getter("MCP_SERVERS", []) or []
    else:
        try:
            raw = store.get("MCP_SERVERS", []) or []
        except AttributeError:
            raw = []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _write_servers(gui, servers: List[dict]) -> None:
    store = settings_store(gui)
    if store is None:
        return
    if callable(getattr(gui, "_save_setting", None)):
        # Сохраняет на диск через событийный контур настроек.
        gui._save_setting("MCP_SERVERS", servers)
        return
    set_setting(gui, "MCP_SERVERS", servers)
    saver = getattr(store, "save_settings", None)
    if callable(saver):
        try:
            saver()
        except Exception:
            pass


def _refresh_tools(gui) -> None:
    service = _mcp_service()
    if service is None:
        return
    try:
        service.refresh_tools()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Диалог редактирования сервера
# ---------------------------------------------------------------------------


class McpServerDialog(QDialog):
    def __init__(self, parent=None, initial: Optional[dict] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("MCP-сервер", "MCP server"))
        self.setMinimumWidth(460)

        self._initial = dict(initial or {})
        self.result_config: Optional[dict] = None

        layout = QVBoxLayout(self)

        form = QFormLayout()

        self.enabled = QCheckBox(_("Включён", "Enabled"))
        self.enabled.setChecked(bool(self._initial.get("enabled", True)))
        layout.addWidget(self.enabled)

        self.name = QLineEdit(str(self._initial.get("name", "")))
        form.addRow(_("Имя", "Name"), self.name)

        self.server_id = QLineEdit(str(self._initial.get("server_id", "")))
        self.server_id.setPlaceholderText(_("уникальный id", "unique id"))
        form.addRow(_("ID", "ID"), self.server_id)

        self.transport = QComboBox()
        self.transport.addItems(["stdio", "http"])
        transport = str(self._initial.get("transport", "stdio")).strip().lower()
        if transport in ("http", "streamable_http"):
            self.transport.setCurrentText("http")
        else:
            self.transport.setCurrentText("stdio")
        self.transport.currentTextChanged.connect(self._on_transport_changed)
        form.addRow(_("Транспорт", "Transport"), self.transport)

        # stdio-поля
        self.command = QLineEdit(str(self._initial.get("command", "")))
        self.command.setPlaceholderText("npx / uvx / python -m ...")
        form.addRow(_("Команда", "Command"), self.command)

        self.args = QTextEdit()
        self.args.setPlainText("\n".join(str(a) for a in (self._initial.get("args") or [])))
        self.args.setFixedHeight(64)
        form.addRow(_("Аргументы (по одному на строку)", "Args (one per line)"), self.args)

        self.env = QTextEdit()
        env_lines = [f"{k}={v}" for k, v in (self._initial.get("env") or {}).items()]
        self.env.setPlainText("\n".join(env_lines))
        self.env.setFixedHeight(64)
        form.addRow(_("Переменные окружения (KEY=VALUE)", "Environment (KEY=VALUE)"), self.env)

        # http-поля
        self.url = QLineEdit(str(self._initial.get("url", "")))
        self.url.setPlaceholderText("https://...")
        form.addRow(_("URL", "URL"), self.url)

        self.headers = QTextEdit()
        header_lines = [f"{k}: {v}" for k, v in (self._initial.get("headers") or {}).items()]
        self.headers.setPlainText("\n".join(header_lines))
        self.headers.setFixedHeight(64)
        form.addRow(_("Заголовки (Key: Value)", "Headers (Key: Value)"), self.headers)

        self.timeout = QLineEdit(str(self._initial.get("timeout", 60)))
        form.addRow(_("Таймаут, сек", "Timeout, s"), self.timeout)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._on_transport_changed(self.transport.currentText())

    def _on_transport_changed(self, transport: str) -> None:
        is_http = transport.startswith("http")
        for widget in (self.command, self.args, self.env):
            widget.setVisible(not is_http)
        for widget in (self.url, self.headers):
            widget.setVisible(is_http)

    def _on_accept(self) -> None:
        transport = self.transport.currentText()
        server_id = str(self.server_id.text()).strip()
        if not server_id:
            # Авто-генерация id из имени, если поле пустое.
            server_id = str(self.name.text()).strip().replace(" ", "_").lower()
        if not server_id:
            server_id = "mcp_server"

        args = [
            line.strip()
            for line in self.args.toPlainText().splitlines()
            if line.strip()
        ]
        env: Dict[str, str] = {}
        for line in self.env.toPlainText().splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()

        headers: Dict[str, str] = {}
        for line in self.headers.toPlainText().splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                headers[key.strip()] = value.strip()

        try:
            timeout = float(self.timeout.text().strip() or 60)
        except (TypeError, ValueError):
            timeout = 60.0

        self.result_config = {
            "server_id": server_id,
            "name": str(self.name.text()).strip() or server_id,
            "transport": transport,
            "enabled": self.enabled.isChecked(),
            "command": str(self.command.text()).strip(),
            "args": args,
            "env": env,
            "url": str(self.url.text()).strip(),
            "headers": headers,
            "timeout": timeout,
        }
        self.accept()


# ---------------------------------------------------------------------------
# Построение раздела
# ---------------------------------------------------------------------------


def _server_row(gui, container: QVBoxLayout, server: dict) -> QWidget:
    row = QWidget()
    row.setObjectName("SettingRow")
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 2, 0, 2)
    lay.setSpacing(8)

    enabled = QCheckBox()
    enabled.setChecked(bool(server.get("enabled", False)))
    transport = str(server.get("transport", "stdio"))

    def _toggle(state) -> None:
        servers = _read_servers(gui)
        for item in servers:
            if item.get("server_id") == server.get("server_id"):
                item["enabled"] = state == 2
        _write_servers(gui, servers)
        _refresh_tools(gui)

    enabled.stateChanged.connect(_toggle)
    lay.addWidget(enabled)

    label = QLabel(f"{server.get('name') or server.get('server_id')}  ({transport})")
    label.setWordWrap(True)
    lay.addWidget(label, 1)

    edit_btn = QPushButton(_("Изменить", "Edit"))
    edit_btn.clicked.connect(lambda: _edit_server(gui, server))
    lay.addWidget(edit_btn)

    del_btn = QPushButton(_("Удалить", "Delete"))
    del_btn.clicked.connect(lambda: _delete_server(gui, server))
    lay.addWidget(del_btn)

    container.addWidget(row)
    return row


def _edit_server(gui, server: dict) -> None:
    dialog = McpServerDialog(gui.parent() if hasattr(gui, "parent") else None, initial=server)
    if dialog.exec() and dialog.result_config is not None:
        servers = _read_servers(gui)
        for i, item in enumerate(servers):
            if item.get("server_id") == server.get("server_id"):
                servers[i] = dialog.result_config
                break
        _write_servers(gui, servers)
        _refresh_tools(gui)
        _rebuild_server_list(gui)


def _delete_server(gui, server: dict) -> None:
    servers = _read_servers(gui)
    servers = [item for item in servers if item.get("server_id") != server.get("server_id")]
    _write_servers(gui, servers)
    _refresh_tools(gui)
    _rebuild_server_list(gui)


def _add_server(gui) -> None:
    dialog = McpServerDialog(gui.parent() if hasattr(gui, "parent") else None)
    if dialog.exec() and dialog.result_config is not None:
        servers = _read_servers(gui)
        servers.append(dialog.result_config)
        _write_servers(gui, servers)
        _refresh_tools(gui)
        _rebuild_server_list(gui)


def _rebuild_server_list(gui) -> None:
    holder = getattr(gui, "_mcp_list_holder", None)
    if holder is None:
        return
    # Очищаем контейнер
    while holder.count():
        item = holder.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
    servers = _read_servers(gui)
    service = _mcp_service()
    tool_count = 0
    enabled_count = 0
    if service is not None:
        try:
            tool_count = len(service.tools_schema() or [])
        except Exception:
            tool_count = 0
    for server in servers:
        if server.get("enabled"):
            enabled_count += 1
        _server_row(gui, holder, server)
    if not servers:
        empty = QLabel(_("Серверы не добавлены. Нажмите «Добавить сервер».", "No servers yet. Click \"Add server\"."))
        holder.addWidget(empty)
        _update_status(gui, enabled_count, tool_count)
        return
    _update_status(gui, enabled_count, tool_count)


def _update_status(gui, enabled_count: int, tool_count: int) -> None:
    label = getattr(gui, "_mcp_status_label", None)
    if label is None:
        return
    label.setText(
        _(
            "Включено серверов: {enabled} · Инструментов: {tools}",
            "Enabled servers: {enabled} · Tools: {tools}",
        ).format(enabled=enabled_count, tools=tool_count)
    )


def setup_mcp_settings_controls(self, parent) -> None:
    """Построить раздел настроек MCP."""
    create_settings_header(parent, "mcp")

    servers = _read_servers(self)
    service = _mcp_service()
    has_sdk = service is not None

    intro = QLabel(
        _(
            "Подключите внешние MCP-серверы, чтобы их инструменты стали доступны "
            "LLM-персонажам (требуется пакет `mcp` в рантайме).",
            "Connect external MCP servers to expose their tools to LLM characters "
            "(requires the `mcp` package in the runtime).",
        )
    )
    intro.setWordWrap(True)
    parent.addWidget(intro)

    if not has_sdk:
        warn = QLabel(
            _(
                "Пакет `mcp` не установлен — серверы работать не будут. Добавьте "
                "его в окружение и перезапустите приложение.",
                "The `mcp` package is not installed — servers will not work. Add "
                "it to the environment and restart the app.",
            )
        )
        warn.setWordWrap(True)
        warn.setObjectName("SeparatorLabel")
        parent.addWidget(warn)

    # Кнопки действий
    actions = QHBoxLayout()
    add_btn = QPushButton(_("Добавить сервер", "Add server"))
    add_btn.clicked.connect(lambda: _add_server(self))
    actions.addWidget(add_btn)

    refresh_btn = QPushButton(_("Обновить инструменты", "Refresh tools"))
    refresh_btn.clicked.connect(lambda: (_refresh_tools(self), _rebuild_server_list(self)))
    actions.addWidget(refresh_btn)

    actions.addStretch(1)
    parent.addLayout(actions)

    status = QLabel()
    status.setObjectName("SeparatorLabel")
    parent.addWidget(status)
    self._mcp_status_label = status

    # Контейнер списка серверов
    holder = QVBoxLayout()
    self._mcp_list_holder = holder
    parent.addLayout(holder)

    _rebuild_server_list(self)
