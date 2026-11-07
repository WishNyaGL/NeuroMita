"""Initiative Gate — Этап 3 (+ Этап 7).

Проверяет ДОПУСТИМОСТЬ инициативы. Gate не формирует мотивы — он лишь
отклоняет недопустимые действия.

На Этапе 7 Gate стал характер- и state-ориентированным: реакция на сигналы
пользователя (goodbye/sleep/busy/do_not_disturb) зависит от характера персонажа
(ReactionPolicy) и текущего внутреннего состояния. Персонаж может: уважить
границу (блокировать), либо переопределить её (не послушаться / просить остаться /
обидеться) — тогда инициатива разрешается.

Занятость персонажа генерацией всегда блокирует (конкуренция генераций).
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from .reaction_policy import ReactionPolicy

# Сигналы, по которым действует ReactionPolicy.
_SIGNAL_SIGNALS = ("goodbye", "sleep", "busy", "do_not_disturb")


class InitiativeGate:
    def __init__(self) -> None:
        pass

    def allow(
        self,
        action: str,
        user_state: Optional[Dict[str, Any]],
        *,
        busy: bool = False,
        internal: Optional[Dict[str, Any]] = None,
        traits: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        """Вернуть (разрешено, причина)."""
        if action != "initiate_dialogue":
            return True, ""

        if busy:
            return False, "character_busy"

        us = user_state if isinstance(user_state, dict) else {}
        signal = us.get("signal")
        if signal not in _SIGNAL_SIGNALS:
            return True, ""

        decision = ReactionPolicy.evaluate(
            str(signal), internal or {}, traits or {}
        )
        if decision.get("respect"):
            return False, f"user_{signal}:{decision.get('reaction')}"
        return True, f"override_{decision.get('reaction')}"
