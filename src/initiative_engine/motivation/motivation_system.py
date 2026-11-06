"""Мотивационная система.

Формирует желания и интересы персонажа на основе воспринятой ситуации, не
заменяя существующую личность числовыми характеристиками. Результат — список
кандидатов-намерений с приоритетом и обоснованием.
"""
from __future__ import annotations

from typing import Any, Dict, List


class MotivationSystem:
    def __init__(self) -> None:
        pass

    def evaluate(
        self,
        perception: Dict[str, Any],
        *,
        personality: str = "",
    ) -> List[Dict[str, Any]]:
        """Оценить ситуацию и вернуть желания/мотивы.

        На этапе 4 — простые эвристики поверх восприятия. Полноценная LLM-оценка
        добавляется позже (DecisionEngine).
        """
        desires: List[Dict[str, Any]] = []
        events = perception.get("events") or []
        working_state = perception.get("working_state") or ""
        window_context = perception.get("window_context") or ""

        # Если есть сообщение/действие — мотив отреагировать/продолжить.
        if events:
            desires.append(
                {
                    "type": "react_to_event",
                    "description": "Реагировать на произошедшее событие",
                    "priority": 3,
                    "source": "events",
                }
            )

        # Если есть незакрытые вопросы в рабочем состоянии — продолжить.
        if "Open loops" in working_state or "focus" in working_state.lower():
            desires.append(
                {
                    "type": "continue_focus",
                    "description": "Продолжить текущий фокус/незакрытый вопрос",
                    "priority": 2,
                    "source": "working_state",
                }
            )

        # Если есть наблюдение за Windows — возможно, спросить/прокомментировать.
        if window_context:
            desires.append(
                {
                    "type": "comment_on_window",
                    "description": f"Прокомментировать наблюдение за экраном: {window_context}",
                    "priority": 1,
                    "source": "window",
                }
            )

        return desires
