"""Состояние взаимодействия с пользователем — Этап 3 (+ доработка).

Оценивает доступность пользователя для самостоятельного взаимодействия на основе
наблюдений: последнее сообщение, события, метки времени.

Определяет сигналы:
- active_conversation — идёт активный разговор;
- goodbye — прощание («пока», «до встречи»);
- sleep — намерение пойти спать;
- busy — занятость/«не сейчас»;
- do_not_disturb — просьба не беспокоить;
- return — возвращение после отсутствия;
- away — явное отсутствие («отойду», «меня не будет»).

Помимо сигналов вычисляется состояние `absent` — пользователь неактивен
(нет действий дольше порога) или явно ушёл. При `absent` движок должен
молчать (не запускать инициативы).

Это только оценка состояния. Разрешение на инициативу принимает InitiativeGate.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, Optional

# Регулярные выражения сигналов (по тексту последнего сообщения пользователя).
_GOODBYE_RE = re.compile(
    r"\b(пока|прощай|до встречи|до связи|бай|goodbye|bye|c у|покедова|всё, пока)\b",
    re.IGNORECASE,
)
_SLEEP_RE = re.compile(
    r"\b(ложусь спать|иду спать|пойду спать|спокойной ночи|сладких снов|спать хочу)\b",
    re.IGNORECASE,
)
_BUSY_RE = re.compile(
    r"\b(занят|занята|не сейчас|позже|сейчас некогда|потом)\b",
    re.IGNORECASE,
)
_DND_RE = re.compile(
    r"\b(не беспокоить|не отвлекай|не трогай|not now|не мешай)\b",
    re.IGNORECASE,
)
_RETURN_RE = re.compile(
    r"\b(вернулся|вернулась|я тут|я здесь|я снова тут|назад)\b",
    re.IGNORECASE,
)
_AWAY_RE = re.compile(
    r"\b(отойду|отойди|отхожу|отходить|меня не будет|буду позже|отошел|отошёл|я отойду|отлучусь)\b",
    re.IGNORECASE,
)

# Порог «активного разговора»: если активность пользователя была недавно.
_ACTIVE_CONVERSATION_WINDOW = 120.0

# Порог «отсутствия»: если активности не было дольше этого времени — пользователь
# не у рабочего места, движок должен молчать. Отвязан от окна разговора.
_ABSENT_THRESHOLD = 300.0


class UserInteractionState:
    def __init__(self) -> None:
        self._last_activity_ts: float = 0.0
        self._last_signal: Optional[str] = None
        self._last_signal_ts: float = 0.0

    # ------------------------------------------------------------- public API

    def update(
        self,
        *,
        last_user_message: Optional[Dict[str, Any]],
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Обновить состояние и вернуть снимок (snapshot)."""
        now = now if now is not None else time.time()
        signal = None
        text = ""
        if isinstance(last_user_message, dict):
            text = str(last_user_message.get("text") or "")
            ts = last_user_message.get("ts")
            if ts:
                self._last_activity_ts = float(ts)
            signal = self._detect_signal(text)
        if signal is not None:
            self._last_signal = signal
            self._last_signal_ts = now
        active = (now - self._last_activity_ts) < _ACTIVE_CONVERSATION_WINDOW
        # Отсутствие: явно отошёл ИЛИ не было активности дольше порога.
        # Если активности ещё не было вовсе (первый запуск) — не считаем отсутствием.
        absent = signal == "away" or (
            self._last_activity_ts > 0
            and (now - self._last_activity_ts) > _ABSENT_THRESHOLD
        )
        return {
            "active_conversation": active,
            "absent": bool(absent),
            "last_activity_ts": self._last_activity_ts,
            "signal": signal or self._last_signal,
            "signal_ts": self._last_signal_ts,
            "last_message": text[:120],
            "label": self._label(signal or self._last_signal),
        }

    # ----------------------------------------------------------- signal detect

    @staticmethod
    def _detect_signal(text: str) -> Optional[str]:
        if not text or not text.strip():
            return None
        # Порядок важен: DND > sleep > busy > away > goodbye > return.
        if _DND_RE.search(text):
            return "do_not_disturb"
        if _SLEEP_RE.search(text):
            return "sleep"
        if _BUSY_RE.search(text):
            return "busy"
        if _AWAY_RE.search(text):
            return "away"
        if _GOODBYE_RE.search(text):
            return "goodbye"
        if _RETURN_RE.search(text):
            return "return"
        return None

    @staticmethod
    def _label(signal: Optional[str]) -> str:
        return {
            "goodbye": "прощание",
            "sleep": "уходит спать",
            "busy": "занят",
            "do_not_disturb": "не беспокоить",
            "return": "вернулся",
            "away": "отошёл",
        }.get(signal, "—")
