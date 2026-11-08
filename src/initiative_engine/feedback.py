"""Feedback: анализ результатов действий и реакции пользователя.

Оценивает, успешно ли выполнилось действие, как отреагировал пользователь,
изменилась ли ситуация, и корректирует намерения (успех/провал/неактуальность).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

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

        Разделяет ДОСТАВКУ действия от ДОСТИЖЕНИЯ цели:
          - delivery: "pending" | "delivered" | "failed";
          - goal: "pending" (ждёт реакции пользователя) | "achieved" | "n/a";
          - action: "keep" | "retry" | "await_reaction" | "complete" | "cancel".

        Отсутствие ответа пользователя НЕ считается ошибкой (user_available).
        """
        outcome = "neutral"
        delivery = "pending"
        goal = "n/a"
        action = "keep"

        text = str(action_result or "").lower()

        # 1. Ошибка исполнения/доставки.
        if action_result is not None and "ошибка" in text:
            outcome = "failed"
            delivery = "failed"
            action = "retry"
        # 2. Доставлено успешно (начат разговор / выполнен инструмент), но цель
        #    ещё не подтверждена пользователем.
        elif delivered and action_result is not None:
            outcome = "success"
            delivery = "delivered"
            goal = "pending"
            action = "await_reaction"
        # 3. Инструмент выполнен без ошибок → цель достигнута.
        elif action_result is not None:
            outcome = "success"
            delivery = "delivered"
            goal = "achieved"
            action = "complete"

        # 4. Пользователь явно отреагировал → цель достигнута.
        if user_reaction:
            outcome = "success"
            goal = "achieved"
            action = "complete"

        # 5. Намерение устарело.
        if event and event.get("stale"):
            outcome = "stale"
            action = "cancel"

        return {
            "outcome": outcome,
            "delivery": delivery,
            "goal": goal,
            "action": action,
            "adjust": None,
        }
