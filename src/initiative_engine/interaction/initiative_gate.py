"""Initiative Gate — Этап 3.

Проверяет ДОПУСТИМОСТЬ инициативы на основе состояния пользователя и среды.
Gate не формирует мотивы и не принимает решения — он лишь отклоняет (gate) те
действия, которые недопустимы в текущем состоянии взаимодействия.

Правила (по умолчанию):
- `initiate_dialogue` запрещён, если пользователь: просил не беспокоить,
  занят, уходит спать или только что попрощался;
- при занятости персонажа генерацией — запрещён;
- остальные действия (например, `act`) Gate по умолчанию пропускает.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


class InitiativeGate:
    def __init__(self) -> None:
        pass

    def allow(
        self,
        action: str,
        user_state: Optional[Dict[str, Any]],
        *,
        busy: bool = False,
    ) -> Tuple[bool, str]:
        """Вернуть (разрешено, причина отказа)."""
        if action != "initiate_dialogue":
            return True, ""

        if busy:
            return False, "character_busy"

        us = user_state if isinstance(user_state, dict) else {}
        signal = us.get("signal")
        if signal == "do_not_disturb":
            return False, "user_do_not_disturb"
        if signal == "busy":
            return False, "user_busy"
        if signal == "sleep":
            return False, "user_sleep"
        if signal == "goodbye":
            return False, "user_goodbye"

        return True, ""
