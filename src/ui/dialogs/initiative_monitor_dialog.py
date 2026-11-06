"""Окно мониторинга Initiative Engine.

Показывает живую статистику движка: конфигурация, тики, события, решения,
действия, намерения, последняя перцепция/решение. Обновляется по таймеру.
"""
from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from utils import _


class InitiativeMonitorDialog(QDialog):
    def __init__(self, engine: Any, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self.setWindowTitle(_("Мониторинг инициативы", "Initiative monitor"))
        self.resize(520, 520)
        self.setMinimumSize(420, 360)

        root = QVBoxLayout(self)

        self._content = QLabel()
        self._content.setWordWrap(True)
        self._content.setTextFormat(Qt.TextFormat.RichText)
        self._content.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._content)
        root.addWidget(scroll, 1)

        refresh_btn = QPushButton(_("Обновить", "Refresh"))
        refresh_btn.clicked.connect(self._refresh)
        root.addWidget(refresh_btn)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

        self._refresh()

    def _refresh(self) -> None:
        try:
            if self._engine is None:
                self._content.setText("(engine not available)")
                return
            stats = self._engine.stats()
            self._content.setText(self._render(stats))
        except Exception as exc:
            self._content.setText(f"<b>error:</b> {exc}")

    def _render(self, s: dict) -> str:
        cfg = s.get("config") or {}
        lines = []
        lines.append(f"<b>{_('Статус', 'Status')}:</b> "
                     f"{_('работает', 'running') if s.get('running') else _('остановлен', 'stopped')}")
        lines.append(f"<b>{_('Движок', 'Engine')}:</b> "
                     f"{_('вкл', 'on') if cfg.get('enabled') else _('выкл', 'off')} "
                     f"· {_('автономность', 'autonomy')}: {cfg.get('autonomy_level')}")
        lines.append(f"<b>{_('Интервал тиков', 'Tick interval')}:</b> "
                     f"{cfg.get('scheduler_interval_sec')}с · "
                     f"{_('действий/мин', 'actions/min')}: {cfg.get('max_actions_per_minute')}")
        lines.append("")
        lines.append(f"<b>{_('Тики', 'Ticks')}:</b> {s.get('ticks')}")
        lines.append(f"<b>{_('События всего', 'Events total')}:</b> {s.get('events_total')} "
                     f"(<b>{_('отфильтровано', 'filtered')}:</b> {s.get('events_filtered')})")
        lines.append(f"<b>{_('Активных намерений', 'Active intentions')}:</b> {s.get('intentions_active')}")
        lines.append("")
        lines.append(f"<b>{_('Решения', 'Decisions')}:</b>")
        decisions = s.get("decisions") or {}
        if decisions:
            for action, count in sorted(decisions.items(), key=lambda kv: -kv[1]):
                lines.append(f"&nbsp;&nbsp;• {action}: {count}")
        else:
            lines.append("&nbsp;&nbsp;—")
        lines.append("")
        last_dec = s.get("last_decision")
        if last_dec:
            lines.append(f"<b>{_('Последнее решение', 'Last decision')}:</b> {last_dec.get('action')} "
                         f"({last_dec.get('reason')}) · {last_dec.get('char')}")
        return "<br>".join(lines)
