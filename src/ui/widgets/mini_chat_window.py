"""Мини-чат окно для свёрнутого приложения.

Плавающее окно снизу-сбоку: показывает реплики персонажей и позволяет быстро
ответить текстом. Показывается только когда главное окно свёрнуто и Unity-игра
не подключена (иначе сообщения дублируются в игре).
"""
from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import Qt, QPoint, QTimer
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from utils import _


class MiniChatWindow(QWidget):
    def __init__(self, main_window: Any, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._main_window = main_window
        self._game_link = None
        self._chat_service = None

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setObjectName("MiniChatWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.resize(340, 420)
        self._dragging = False
        self._drag_offset = None
        self._user_closed = False

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        title = QLabel(_("Быстрый чат", "Quick chat"))
        title.setObjectName("MiniChatTitle")
        header.addWidget(title, 1)

        close_btn = QPushButton("×")
        close_btn.setObjectName("MiniChatClose")
        close_btn.setFixedSize(22, 22)
        close_btn.clicked.connect(self._hide_until_restore)
        header.addWidget(close_btn)
        root.addLayout(header)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setObjectName("MiniChatLog")
        root.addWidget(self._log, 1)

        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText(_("Быстрый ответ...", "Quick reply..."))
        self._input.returnPressed.connect(self._send)
        input_row.addWidget(self._input, 1)

        send_btn = QPushButton(_("Отправить", "Send"))
        send_btn.clicked.connect(self._send)
        input_row.addWidget(send_btn)
        root.addLayout(input_row)

        self._check_timer = QTimer(self)
        self._check_timer.setInterval(500)
        self._check_timer.timeout.connect(self._maybe_toggle)
        self._check_timer.start()

    # ----------------------------------------------------------------- setup

    def bind(self, game_link: Any, chat_service: Any) -> None:
        self._game_link = game_link
        self._chat_service = chat_service

    def append_message(self, character_name: str, text: str, *, user: bool = False) -> None:
        if user:
            self._log.append(f"<i style='color:#888'>Вы:</i> {text}")
        else:
            self._log.append(f"<b>{character_name}:</b> {text}")
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum()
        )

    def append_user_message(self, text: str) -> None:
        self.append_message("", text, user=True)

    # -------------------------------------------------------------- visibility

    def _is_main_minimized(self) -> bool:
        try:
            if self._main_window is None:
                return False
            return bool(self._main_window.isMinimized())
        except Exception:
            return False

    def _is_game_connected(self) -> bool:
        if self._game_link is None:
            return False
        try:
            return bool(self._game_link.is_connected())
        except Exception:
            return False

    def _maybe_toggle(self) -> None:
        should_show = self._is_main_minimized() and not self._is_game_connected()
        if not should_show:
            # Окно развёрнуто или игра запущена — скрываем и сбрасываем «закрыто».
            self._user_closed = False
            if self.isVisible():
                self.hide()
            return
        if self._user_closed:
            # Пользователь сам закрыл окно — не показываем до разворачивания.
            return
        if not self.isVisible():
            self.show()
            self.raise_()

    def _hide_until_restore(self) -> None:
        self._user_closed = True
        self.hide()

    # ------------------------------------------------------------- input

    def _send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.append_user_message(text)
        if self._chat_service is not None:
            try:
                from services.contracts import CharacterRegistry
                from core.services import services

                registry = services().get_optional(CharacterRegistry)
                char_id = registry.current_id() if registry else ""
                if char_id:
                    self._chat_service.reply(
                        character_id=char_id,
                        message_id="mini_chat",
                        user_input=text,
                    )
            except Exception:
                pass

    # ------------------------------------------------------------ dragging

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging and self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)
