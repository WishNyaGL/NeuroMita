"""Окно мониторинга Initiative Engine.

Показывает живую статистику движка: конфигурация, тики, события, решения,
действия, намерения, последняя перцепция/решение. Обновляется по таймеру.
"""
from __future__ import annotations

import html
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

    @staticmethod
    def _esc(value: Any) -> str:
        return html.escape(str(value if value is not None else ""))

    @staticmethod
    def _fmt_ts(ts: Optional[float]) -> str:
        if not ts:
            return "—"
        try:
            import time as _time
            return _time.strftime("%H:%M:%S", _time.localtime(float(ts)))
        except Exception:
            return "—"

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
        # ── Числовое внутреннее состояние (любопытство и т.п.) ──────────────
        internal_state = s.get("internal_state") or {}
        if internal_state:
            lines.append("")
            lines.append(f"<b>{_('Состояние', 'Internal state')}:</b>")
            for k, v in sorted(internal_state.items()):
                lines.append(f"&nbsp;&nbsp;• {self._esc(k)}: <b>{self._esc(v)}</b>")

        # ── Последний анализ (perception) ────────────────────────────────────
        last_perc = s.get("last_perception") or {}
        if last_perc:
            lines.append("")
            lines.append(f"<b>{_('Анализ (последний)', 'Last analysis')}:</b>")
            lines.append(
                f"&nbsp;&nbsp;• {_('персонаж', 'character')}: "
                f"{self._esc(last_perc.get('character_id'))} · "
                f"{_('уверенность', 'confidence')}: {self._esc(last_perc.get('confidence'))}"
            )
            topic = last_perc.get("topic")
            if topic:
                lines.append(f"&nbsp;&nbsp;• {_('тема', 'topic')}: "
                             f"{self._esc(topic[:120])}")
            oloops = last_perc.get("open_loops") or []
            if oloops:
                lines.append(f"&nbsp;&nbsp;• {_('открытые вопросы', 'open loops')}:")
                for o in oloops[:4]:
                    lines.append(f"&nbsp;&nbsp;&nbsp;&nbsp;• {self._esc(o[:120])}")
            summary = last_perc.get("summary") or ""
            if summary:
                lines.append(f"&nbsp;&nbsp;• {_('сводка', 'summary')}: "
                             f"{self._esc(summary[:160])}")
            wstate = last_perc.get("working_state") or ""
            if wstate:
                lines.append(f"&nbsp;&nbsp;• {_('working state', 'working state')}: "
                             f"{self._esc(wstate[:200])}")
            wctx = last_perc.get("window_context") or ""
            if wctx:
                lines.append(f"&nbsp;&nbsp;• {_('окно', 'window')}: "
                             f"{self._esc(wctx[:120])}")
            memories = last_perc.get("memories") or []
            if memories:
                lines.append(f"&nbsp;&nbsp;• {_('память', 'memory')}: "
                             f"{self._esc(str(memories[0])[:120])}")

        # ── Проанализированные события ───────────────────────────────────────
        last_events = s.get("last_events") or []
        if last_events:
            lines.append("")
            lines.append(f"<b>{_('События анализа', 'Analyzed events')} "
                         f"({len(last_events)}):</b>")
            for ev in last_events[-8:]:
                etype = self._esc(ev.get("type"))
                esource = self._esc(ev.get("source") or "?")
                edata = ev.get("data") or {}
                etxt = self._esc(edata.get("tool_name") or edata.get("summary") or "")
                lines.append(
                    f"&nbsp;&nbsp;• [{esource}] {etype}"
                    + (f" — {etxt[:60]}" if etxt else "")
                )

        # ── Состояние пользователя (Этап 3) ──────────────────────────────────
        user_state = s.get("user_state") or {}
        if user_state:
            lines.append("")
            lines.append(f"<b>{_('Пользователь', 'User state')}:</b>")
            lines.append(
                f"&nbsp;&nbsp;• {_('активный разговор', 'active conv')}: "
                f"{self._esc(user_state.get('active_conversation'))} · "
                f"{_('сигнал', 'signal')}: {self._esc(user_state.get('label'))}"
            )
        # Характер персонажа (Этап 7).
        traits = s.get("traits") or {}
        if traits:
            lines.append(
                f"&nbsp;&nbsp;• {_('характер', 'traits')}: "
                f"{', '.join(f'{k}={v}' for k, v in sorted(traits.items()))}"
            )

        # ── Мотивы ───────────────────────────────────────────────────────────
        motives = s.get("last_motives") or []
        if motives:
            lines.append("")
            lines.append(f"<b>{_('Мотивы', 'Motives')}:</b>")
            for m in motives:
                lines.append(
                    f"&nbsp;&nbsp;• {self._esc(m.get('type'))} "
                    f"(priority {self._esc(m.get('priority'))}, "
                    f"source {self._esc(m.get('source'))})"
                )
        else:
            lines.append("")
            lines.append(f"<b>{_('Мотивы', 'Motives')}:</b> —")

        # ── Решения ──────────────────────────────────────────────────────────
        lines.append("")
        lines.append(f"<b>{_('Решения', 'Decisions')}:</b>")
        decisions = s.get("decisions") or {}
        if decisions:
            for action, count in sorted(decisions.items(), key=lambda kv: -kv[1]):
                lines.append(f"&nbsp;&nbsp;• {self._esc(action)}: {count}")
        else:
            lines.append("&nbsp;&nbsp;—")
        last_dec = s.get("last_decision")
        if last_dec:
            lines.append(
                f"&nbsp;&nbsp;{_('последнее', 'last')}: "
                f"{self._esc(last_dec.get('action'))} "
                f"({self._esc(last_dec.get('reason'))}) · {self._esc(last_dec.get('char'))}"
            )

        # ── Что предпринято (последнее действие) ─────────────────────────────
        last_action = s.get("last_action")
        if last_action:
            lines.append("")
            lines.append(f"<b>{_('Последнее действие', 'Last action')}:</b>")
            status = self._esc(last_action.get("status"))
            lines.append(
                f"&nbsp;&nbsp;• {self._esc(last_action.get('action'))} [{status}] "
                f"· {self._esc(last_action.get('character_id'))} "
                f"· {self._fmt_ts(last_action.get('ts'))}"
            )
            if last_action.get("reason"):
                lines.append(f"&nbsp;&nbsp;& {_('причина', 'reason')}: "
                             f"{self._esc(last_action.get('reason'))}")
            if last_action.get("detail"):
                lines.append(f"&nbsp;&nbsp;• {_('результат', 'result')}: "
                             f"{self._esc(last_action.get('detail'))[:160]}")

        # ── Намерения ────────────────────────────────────────────────────────
        intentions = s.get("intentions") or []
        lines.append("")
        lines.append(f"<b>{_('Намерения', 'Intentions')} "
                     f"({len(intentions)}):</b>")
        if intentions:
            for it in intentions:
                lines.append(
                    f"&nbsp;&nbsp;• {self._esc(it.get('type'))} "
                    f"[{self._esc(it.get('status'))}] "
                    f"priority {self._esc(it.get('priority'))} "
                    f"· {self._esc(it.get('character_id'))}"
                )
                if it.get("description"):
                    lines.append(f"&nbsp;&nbsp;&nbsp;&nbsp;{self._esc(it.get('description'))[:120]}")
        else:
            lines.append("&nbsp;&nbsp;—")

        # ── Инициативы в полёте ──────────────────────────────────────────────
        inflight = s.get("in_flight_initiative") or {}
        if inflight:
            lines.append("")
            lines.append(f"<b>{_('Инициативы в полёте', 'In-flight initiatives')}:</b>")
            for cid, ts in sorted(inflight.items()):
                lines.append(f"&nbsp;&nbsp;• {self._esc(cid)} · {self._fmt_ts(ts)}")

        return "<br>".join(lines)
