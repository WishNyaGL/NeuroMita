"""Мини-чат окно для свёрнутого приложения + сворачивание в иконку Миты.

Основное окно показывает реплики персонажей и быстрые ответы. Его можно
свернуть в иконку персонажа (аватар). Из иконки выскакивают облачка с
сообщениями; клик по облачку разворачивает окно обратно. Работает только когда
главное окно свёрнуто и Unity-игра не подключена.
"""
from __future__ import annotations

import html
from typing import Any, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QPixmap
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

# Средняя скорость чтения: ~200 слов/мин = ~3.3 слова/сек.
_WORDS_PER_SEC = 3.3

# Цвет акцента для имён (розовый).
_NAME_COLOR = "#ff8ab0"

# QSS мини-чата в общем стиле NeuroMita (тёмные панели + розовый акцент).
_MINI_CHAT_QSS = r"""
#MiniChatWindow {
    background-color: rgba(14, 16, 31, 0.98);
    border: 1px solid rgba(40, 38, 54, 0.85);
}
QLabel#MiniChatTitle {
    color: #f3edf6;
    font-weight: 700;
    font-size: 10pt;
}
QPushButton#MiniChatCollapse, QPushButton#MiniChatExpand {
    background-color: #080912;
    color: #f3edf6;
    border: 1px solid rgba(255, 255, 255, 0.06);
    border-radius: 8px;
    padding: 2px 10px;
    font-size: 8.5pt;
    font-weight: 600;
}
QPushButton#MiniChatCollapse:hover, QPushButton#MiniChatExpand:hover { background-color: rgba(183, 75, 125, 0.12); }
QPushButton#MiniChatCollapse:pressed, QPushButton#MiniChatExpand:pressed { background-color: rgba(183, 75, 125, 0.18); }
QPushButton#MiniChatClose {
    background-color: transparent;
    color: #bca9bb;
    border: none;
    border-radius: 6px;
    font-size: 14pt;
    font-weight: 600;
}
QPushButton#MiniChatClose:hover { background-color: rgba(214, 69, 69, 0.16); color: #ffb4b4; }
QPushButton#MiniChatClose:pressed { background-color: rgba(214, 69, 69, 0.26); }
QTextEdit#MiniChatLog {
    background-color: #080912;
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 10px;
    padding: 6px;
    color: #f3edf6;
    selection-background-color: #b74b7d;
    selection-color: #ffffff;
}
QLineEdit#MiniChatInput {
    background-color: #080912;
    border: 1px solid rgba(255, 255, 255, 0.07);
    border-radius: 10px;
    padding: 6px 10px;
    color: #f3edf6;
    selection-background-color: #b74b7d;
    selection-color: #ffffff;
}
QLineEdit#MiniChatInput:focus { border: 1px solid #b74b7d; }
QPushButton#MiniChatSend {
    background-color: #b74b7d;
    color: #ffffff;
    border: 1px solid rgba(130, 56, 88, 0.55);
    border-radius: 10px;
    padding: 6px 14px;
    font-weight: 600;
}
QPushButton#MiniChatSend:hover { background-color: #c04c80; }
QPushButton#MiniChatSend:pressed { background-color: #a0436c; }
"""


def _message_visible_ms(text: str) -> int:
    """Время показа облачка: (длина/скорость чтения) * 2, мин. 3с."""
    words = max(1, len(str(text or "").split()))
    ms = int((words / _WORDS_PER_SEC) * 1000 * 2)
    return max(3000, ms)


class BubbleWindow(QWidget):
    """Облачко сообщения — отдельное окно рядом с иконкой (не обрезается)."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("MitaBubbleWindow")
        self.setStyleSheet(
            "QWidget#MitaBubbleWindow { background-color: rgba(20, 22, 40, 0.97);"
            " color:#f3edf6;"
            " border:1px solid rgba(255, 255, 255, 0.08); }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        self._label = QLabel(self)
        self._label.setObjectName("MitaBubbleLabel")
        self._label.setWordWrap(True)
        self._label.setStyleSheet("background: transparent; border: none; color: #f3edf6;")
        lay.addWidget(self._label)
        self._on_click = None

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_round_mask()

    def _apply_round_mask(self) -> None:
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QPainterPath, QRegion

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), 12, 12)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def set_click_callback(self, callback) -> None:
        self._on_click = callback

    def set_text(self, text: str) -> None:
        self._label.setText(str(text or ""))
        self.adjustSize()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._on_click is not None:
            self._on_click()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class CometRing(QWidget):
    """Анимированное кольцо-комета по ободу иконки (оверлей поверх аватара)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._angle = 0.0
        self._active = False

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self.update()

    def set_angle(self, angle: float) -> None:
        self._angle = angle
        self.update()

    def paintEvent(self, event) -> None:
        if not self._active:
            return
        import math
        from PyQt6.QtCore import QRectF, QPointF
        from PyQt6.QtGui import QPainter, QColor, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        radius = min(w, h) / 2.0 - 4.0
        rect = QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)

        # Два симметричных «хвоста» на противоположных сторонах обода — оба
        # вращаются в одну сторону, поэтому картинка выглядит согласованно.
        tail_span = 80.0
        for offset in (0.0, 180.0):
            a = self._angle + offset
            start = a - tail_span
            pen = QPen(QColor(255, 138, 176, 140))
            pen.setWidth(4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(rect, int(start * 16), int(tail_span * 16))

            rad = math.radians(a)
            hx = cx + radius * math.cos(rad)
            hy = cy + radius * math.sin(rad)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 138, 176, 230))
            painter.drawEllipse(QPointF(hx, hy), 3.0, 3.0)
        painter.end()


class MitaIcon(QWidget):
    """Маленькая иконка персонажа с облачками сообщений."""

    def __init__(self, parent_q: Any = None) -> None:
        super().__init__(None)  # независимое окно
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("MitaIcon")
        self.resize(64, 64)

        self._avatar = QLabel(self)
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setGeometry(0, 0, 64, 64)
        self._avatar.setObjectName("MitaIconAvatar")

        # Облачко — отдельное окно рядом с иконкой.
        self._bubble = BubbleWindow()
        self._bubble.set_click_callback(self._expand)

        # Индикатор «думает» — комета по ободу иконки (оверлей над аватаром).
        self._comet = CometRing(self)
        self._comet.setGeometry(0, 0, 64, 64)
        self._comet.raise_()
        self._comet_angle = 0.0
        self._think_timer = QTimer(self)
        self._think_timer.setInterval(33)
        self._think_timer.timeout.connect(self._advance_thinking)

        self._dragging = False
        self._drag_offset = None
        self._moved = False
        self._press_pos = None
        self._user_hidden = False
        self._bubble_timer = QTimer(self)
        self._bubble_timer.setSingleShot(True)
        self._bubble_timer.timeout.connect(self._hide_bubble)

        # Прозрачный фон: иначе глобальный QSS красит окно в bg_root (тёмный квадрат).
        self.setStyleSheet("QWidget#MitaIcon { background: transparent; }")

        self._on_expand = None

    def set_expand_callback(self, callback) -> None:
        self._on_expand = callback

    def _expand(self) -> None:
        if self._on_expand is not None:
            self._on_expand()

    # ------------------------------------------------------------- avatar

    def set_character(self, character_name: str) -> None:
        try:
            from ui.chat.message_widget import resolve_character_avatar

            pix = resolve_character_avatar(character_name, 64)
            if pix is not None and not pix.isNull():
                self._avatar.setPixmap(pix.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                return
        except Exception:
            pass
        self._avatar.setText(character_name[:1].upper())

    # ---------------------------------------------------------- bubble

    def show_bubble(self, text: str) -> None:
        # Облачко показываем только когда иконка открыта (свёрнуто в неё).
        if not self.isVisible():
            return
        self._bubble.set_text(text)
        self._place_bubble()
        self._bubble.show()
        self._bubble.raise_()
        self._bubble_timer.start(_message_visible_ms(text))

    def _hide_bubble(self) -> None:
        self._bubble.hide()

    def _place_bubble(self, win: Optional[QWidget] = None) -> None:
        from PyQt6.QtGui import QGuiApplication

        win = win or self._bubble
        icon_geom = self.frameGeometry()
        x = icon_geom.right() + 8
        y = icon_geom.center().y() - win.height() // 2
        screen = QGuiApplication.screenAt(icon_geom.center())
        if screen is not None:
            sg = screen.availableGeometry()
            if x + win.width() > sg.right():
                x = icon_geom.left() - win.width() - 8
            y = max(sg.top(), min(y, sg.bottom() - win.height()))
        win.move(x, y)

    # ---------------------------------------------------------- thinking

    def show_thinking(self) -> None:
        if not self.isVisible():
            return
        self._comet_angle = 0.0
        self._comet.set_angle(0.0)
        self._comet.set_active(True)
        self._think_timer.start()

    def hide_thinking(self) -> None:
        self._think_timer.stop()
        self._comet.set_active(False)

    def _advance_thinking(self) -> None:
        self._comet_angle = (self._comet_angle + 14.0) % 360.0
        self._comet.set_angle(self._comet_angle)

    # ---------------------------------------------------------- visibility

    def show_icon(self) -> None:
        if self._user_hidden:
            return
        self.show()
        self.raise_()

    def hide_icon(self) -> None:
        self.hide()
        self._bubble_timer.stop()
        self._bubble.hide()
        self.hide_thinking()

    def set_user_hidden(self, hidden: bool) -> None:
        self._user_hidden = bool(hidden)

    def contextMenuEvent(self, event) -> None:
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        act_open = menu.addAction(_("Открыть чат", "Open chat"))
        act_hide = menu.addAction(_("Скрыть", "Hide"))
        chosen = menu.exec(event.globalPos())
        if chosen == act_open and self._on_expand is not None:
            self._on_expand()
        elif chosen == act_hide:
            self.set_user_hidden(True)
            self.hide_icon()

    # ---------------------------------------------------------- dragging

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._moved = False
            self._press_pos = event.globalPosition().toPoint()
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging and self._drag_offset is not None:
            if (event.globalPosition().toPoint() - self._press_pos).manhattanLength() >= 4:
                self._moved = True
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            if self._bubble.isVisible():
                self._place_bubble()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._on_expand is not None:
            self._on_expand()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class MiniChatWindow(QWidget):
    # Сигналы для кросс-поточной маршализации: UI-обновления всегда выполняются
    # в GUI-потоке (квированы через Qt), даже если вызваны из фонового потока.
    messageRequested = pyqtSignal(str, str, bool)  # character_name/"" , text, is_user
    characterRequested = pyqtSignal(str)  # character_name
    errorRequested = pyqtSignal(str, str)  # message, name
    thinkingStarted = pyqtSignal(str)  # character_name
    thinkingStopped = pyqtSignal()

    def __init__(self, main_window: Any, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._main_window = main_window
        self._game_link = None
        self._chat_service = None
        self._character_name = "Mita"
        self._typing_name = "Mita"

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
        self._saved_icon_pos = None

        self._icon = MitaIcon()
        self._icon.set_expand_callback(self._expand_from_icon)
        self.messageRequested.connect(self._on_message)
        self.characterRequested.connect(self._on_character)
        self.errorRequested.connect(self._on_error)
        self.thinkingStarted.connect(self._on_thinking_started)
        self.thinkingStopped.connect(self._on_thinking_stopped)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        title = QLabel(_("Быстрый чат", "Quick chat"))
        title.setObjectName("MiniChatTitle")
        header.addWidget(title, 1)

        expand_btn = QPushButton(_("Развернуть", "Expand"))
        expand_btn.setObjectName("MiniChatExpand")
        expand_btn.setFixedHeight(22)
        expand_btn.clicked.connect(self._expand_main_window)
        header.addWidget(expand_btn)

        collapse_btn = QPushButton(_("Свернуть", "Collapse"))
        collapse_btn.setObjectName("MiniChatCollapse")
        collapse_btn.setFixedHeight(22)
        collapse_btn.clicked.connect(self._collapse_to_icon)
        header.addWidget(collapse_btn)

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

        self._typing_label = QLabel()
        self._typing_label.setObjectName("MiniChatTyping")
        self._typing_label.setStyleSheet(
            f"color:{_NAME_COLOR}; font-style:italic; padding:2px 0 2px 0;"
        )
        self._typing_label.hide()
        root.addWidget(self._typing_label)

        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setObjectName("MiniChatInput")
        self._input.setPlaceholderText(_("Быстрый ответ...", "Quick reply..."))
        self._input.returnPressed.connect(self._send)
        input_row.addWidget(self._input, 1)

        send_btn = QPushButton(_("Отправить", "Send"))
        send_btn.setObjectName("MiniChatSend")
        send_btn.clicked.connect(self._send)
        input_row.addWidget(send_btn)
        root.addLayout(input_row)

        self.setStyleSheet(_MINI_CHAT_QSS)

        self._check_timer = QTimer(self)
        self._check_timer.setInterval(500)
        self._check_timer.timeout.connect(self._maybe_toggle)
        self._check_timer.start()

    # ----------------------------------------------------------------- setup

    def bind(self, game_link: Any, chat_service: Any) -> None:
        self._game_link = game_link
        self._chat_service = chat_service

    def set_character(self, character_name: str) -> None:
        self.characterRequested.emit(character_name)

    def _on_character(self, character_name: str) -> None:
        self._character_name = character_name or "Mita"
        self._icon.set_character(self._character_name)
        self.setWindowTitle(self._character_name)

    def append_message(self, character_name: str, text: str, *, user: bool = False) -> None:
        self.messageRequested.emit(character_name, text, bool(user))

    def append_user_message(self, text: str) -> None:
        self.append_message("", text, user=True)

    def _on_message(self, character_name: str, text: str, is_user: bool) -> None:
        safe = html.escape(str(text))
        if is_user:
            body = f"<span style='color:{_NAME_COLOR};'>Вы:</span> {safe}"
        else:
            nm = html.escape(str(character_name))
            body = f"<b style='color:{_NAME_COLOR};'>{nm}:</b> {safe}"
        self._log.append(f"<p style='margin:0 0 6px 0;'>{body}</p>")
        if not is_user:
            self._icon.show_bubble(text)
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum()
        )

    def append_error(self, message: str, name: str = "") -> None:
        self.errorRequested.emit(message, name)

    def _on_error(self, message: str, name: str = "") -> None:
        m = html.escape(str(message))
        nm = html.escape(str(name)) or "Система"
        self._log.append(
            f"<p style='margin:0 0 6px 0;color:#e06c6c;font-style:italic;'>"
            f"<b>{nm}:</b> {m}</p>"
        )
        self._log.verticalScrollBar().setValue(
            self._log.verticalScrollBar().maximum()
        )

    def start_thinking(self, name: str = "") -> None:
        self.thinkingStarted.emit(name)

    def _on_thinking_started(self, name: str = "") -> None:
        if name:
            self._typing_name = name
        self._icon.show_thinking()
        if self.isVisible():
            self._typing_label.setText(f"{self._typing_name} думает…")
            self._typing_label.show()

    def stop_thinking(self) -> None:
        self.thinkingStopped.emit()

    def _on_thinking_stopped(self) -> None:
        self._icon.hide_thinking()
        self._typing_label.hide()

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
            self._user_closed = False
            self._icon.set_user_hidden(False)
            self._icon.hide_icon()
            if self.isVisible():
                self.hide()
            return
        # Свёрнуто и не игра: показываем иконку (или окно, если оно раскрыто).
        if self.isVisible():
            return
        if self._user_closed:
            self._icon.show_icon()
            self._saved_icon_pos = self._icon.pos()
            return
        # Окно свернуто в иконку — показываем иконку.
        self._icon.show_icon()
        self._saved_icon_pos = self._icon.pos()

    def _collapse_to_icon(self) -> None:
        self.hide()
        self._icon.set_user_hidden(False)
        self._icon.show_icon()
        if self._saved_icon_pos is not None:
            self._icon.move(self._clamp_icon_pos(self._saved_icon_pos))
        else:
            self._place_icon_center()

    def _expand_main_window(self) -> None:
        """Развернуть основное окно приложения (если оно свёрнуто)."""
        try:
            if self._main_window is None:
                return
            if self._main_window.isMinimized():
                self._main_window.showNormal()
            self._main_window.show()
            self._main_window.raise_()
            self._main_window.activateWindow()
        except Exception:
            pass

    def _expand_from_icon(self) -> None:
        if self._icon.isVisible():
            self._saved_icon_pos = self._icon.pos()
        self._icon.hide_icon()
        self._user_closed = False
        self.show()
        self._center_chat_on_icon()
        self.raise_()

    def _center_chat_on_icon(self) -> None:
        """Расположить окно чата по центру иконки (у краёв подстраивается под экран)."""
        from PyQt6.QtGui import QGuiApplication

        icon_geom = self._icon.frameGeometry()
        w, h = self.width(), self.height()
        x = icon_geom.center().x() - w // 2
        y = icon_geom.center().y() - h // 2
        screen = QGuiApplication.screenAt(icon_geom.center())
        if screen is not None:
            sg = screen.availableGeometry()
            x = max(sg.left(), min(x, sg.right() - w))
            y = max(sg.top(), min(y, sg.bottom() - h))
        self.move(x, y)

    def _place_icon_center(self) -> None:
        """Иконка по центру окна чата (используется, когда позиция не сохранена)."""
        geom = self.frameGeometry()
        ic = self._icon
        ic.move(
            geom.center().x() - ic.width() // 2,
            geom.center().y() - ic.height() // 2,
        )

    def _clamp_icon_pos(self, pos) -> Any:
        from PyQt6.QtCore import QPoint
        from PyQt6.QtGui import QGuiApplication

        ic = self._icon
        screen = QGuiApplication.screenAt(ic.frameGeometry().center())
        if screen is None:
            return QPoint(max(0, pos.x()), max(0, pos.y()))
        ag = screen.availableGeometry()
        x = max(ag.left(), min(pos.x(), ag.right() - ic.width()))
        y = max(ag.top(), min(pos.y(), ag.bottom() - ic.height()))
        return QPoint(x, y)

    def _hide_until_restore(self) -> None:
        self._user_closed = True
        self._icon.set_user_hidden(True)
        self.hide()
        self._icon.hide_icon()

    def contextMenuEvent(self, event) -> None:
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        act_collapse = menu.addAction(_("Свернуть в иконку", "Collapse into icon"))
        act_hide = menu.addAction(_("Скрыть", "Hide"))
        chosen = menu.exec(event.globalPos())
        if chosen == act_collapse:
            self._collapse_to_icon()
        elif chosen == act_hide:
            self._hide_until_restore()

    # ------------------------------------------------------------- input

    def _send(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        try:
            from core.services import services
            from services.contracts import CharacterRegistry

            registry = services().get_optional(CharacterRegistry)
            char_id = registry.current_id() if registry else ""
            if char_id:
                # Отправляем через общий конвейер (shell_actions.send_message),
                # чтобы использовать единый message_id и избежать дублей.
                # Сообщение в мини-чате покажется через нормальный путь обновления чата.
                main = self._main_window
                if main is not None and hasattr(main, "_shell_actions"):
                    shell_actions = main._shell_actions
                    if shell_actions is not None:
                        shell_actions.send_message(
                            user_input=text,
                            trace_id=None,
                            merge_input_from_entry=False,
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
