"""Feedback: анализ результатов действий и реакции пользователя.

Оценивает, успешно ли выполнилось действие, как отреагировал пользователь,
изменилась ли ситуация, и корректирует намерения (успех/провал/неактуальность).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from main_logger import logger


class FeedbackSystem:
    def __init__(self) -> None:
        pass

    def process(
        self,
        *,
        intention: Dict[str, Any],
        action_result: Optional[str] = None,
        user_reaction: Optional[str] = None,
        event: Optional[Dict[str, Any]] = None,
        delivered: bool = False,
        user_available: bool = True,
    ) -> Dict[str, Any]:
        """Проанализировать результат попытки/действия.

        Возвращает:
          - outcome: "success" | "failed" | "stale" | "neutral"
          - adjust: новый приоритет (или None)
          - action: "complete" | "retry" | "cancel" | "keep"
        """
        outcome = "neutral"
        action = "keep"

        # Инструмент завершился ошибкой.
        if action_result is not None and "ошибка" in str(action_result).lower():
            outcome = "failed"
            action = "retry"
        elif action_result is not None and str(action_result).startswith("[InitiativeAction]"):
            outcome = "failed"
            action = "retry"

        # Действие было успешно доставлено (начат разговор / выполнен инструмент).
        # Отсутствие ответа пользователя НЕ считается ошибкой (user_available).
        if delivered and action_result is not None:
            if "ошибка" not in str(action_result).lower():
                outcome = "success"
                action = "complete"

        # Пользователь явно отреагировал — считаем действие успешным.
        if user_reaction:
            outcome = "success"
            action = "complete"

        # Намерение устарело.
        if event and event.get("stale"):
            outcome = "stale"
            action = "cancel"

        return {
            "outcome": outcome,
            "adjust": None,
            "action": action,
        }
