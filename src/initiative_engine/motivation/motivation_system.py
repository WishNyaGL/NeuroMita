"""Мотивационная система — Этап 5.

Формирует желания персонажа на основе воспринятой ситуации и внутреннего состояния.
Motivation определяет, ЧЕГО персонаж хочет; Decision решает, стоит ли реализовывать
это сейчас.

Мотивы (типы):
- react_to_event              — реакция на значимое событие;
- continue_conversation        — продолжить активный разговор;
- ask_followup                 — задать уточняющий вопрос;
- return_to_unfinished_topic   — вернуться к незакрытому вопросу;
- comment_on_environment       — прокомментировать наблюдение за экраном;
- want_to_interact             — желание взаимодействовать (скучно);
- share_thought                — поделиться мыслью по наблюдению.

Учитывается внутреннее состояние (perception["internal_state"]): boredom, stress,
curiosity. Не создаёт дублирующих типов.
"""
from __future__ import annotations

from typing import Any, Dict, List

# Пороги внутреннего состояния.
_BOREDOM_WANT_INTERACT = 0.6
_STRESS_STOP = 0.7
_CURIOSITY_COMMENT = 0.5
_CURIOSITY_SHARE = 0.5


class MotivationSystem:
    def __init__(self) -> None:
        pass

    def evaluate(
        self,
        perception: Dict[str, Any],
        *,
        personality: str = "",
    ) -> List[Dict[str, Any]]:
        """Оценить ситуацию и вернуть желания/мотивы (по убыванию приоритета)."""
        events = perception.get("events") or []
        working_state = perception.get("working_state") or ""
        window_context = perception.get("window_context") or ""
        open_loops = perception.get("open_loops") or []
        internal = perception.get("internal_state") or {}

        boredom = float(internal.get("boredom", 0.1))
        stress = float(internal.get("stress", 0.05))
        curiosity = float(internal.get("curiosity", 0.2))

        desires: List[Dict[str, Any]] = []

        # Значимые события → реакция/мысль.
        significant = [e for e in events if e.get("significance", 0) >= 0.5]
        if significant:
            desires.append(
                {
                    "type": "react_to_event",
                    "description": "Реагировать на значимое событие",
                    "priority": 3,
                    "source": "events",
                }
            )

        # Открытые вопросы → вернуться / задать вопрос.
        if open_loops:
            desires.append(
                {
                    "type": "return_to_unfinished_topic",
                    "description": "Вернуться к незакрытому вопросу",
                    "priority": 3,
                    "source": "working_state",
                }
            )
            desires.append(
                {
                    "type": "ask_followup",
                    "description": "Задать уточняющий вопрос",
                    "priority": 2,
                    "source": "events",
                }
            )

        # Наблюдение за окном + любопытство → комментарий/действие.
        if window_context:
            prio = 2 if curiosity >= _CURIOSITY_COMMENT else 1
            desires.append(
                {
                    "type": "comment_on_environment",
                    "description": f"Прокомментировать экран: {window_context[:80]}",
                    "priority": prio,
                    "source": "window",
                }
            )

        # Внутреннее состояние.
        if boredom >= _BOREDOM_WANT_INTERACT and stress < _STRESS_STOP:
            desires.append(
                {
                    "type": "want_to_interact",
                    "description": "Хочется взаимодействовать (скучно)",
                    "priority": 3,
                    "source": "working_state",
                }
            )
        if curiosity >= _CURIOSITY_SHARE and significant:
            desires.append(
                {
                    "type": "share_thought",
                    "description": "Поделиться мыслью по наблюдению",
                    "priority": 2,
                    "source": "events",
                }
            )

        desires.sort(key=lambda m: -int(m.get("priority", 0)))
        return desires
