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

        # Последнее сообщение персонажа — вопрос, НЕ отвеченный пользователем:
        # логично переспросить/продолжить тему (например «что молчишь?»).
        # Чтобы не зациклиться, вопрос считается актуальным ТОЛЬКО если он
        # задан ПОСЛЕ последнего сообщения пользователя (т.е. ответа ещё нет).
        last_assistant = perception.get("last_assistant_message") or {}
        last_user = perception.get("last_user_message") or {}
        assistant_text = str(last_assistant.get("text") or "")
        assistant_ts = float(last_assistant.get("ts") or 0)
        user_ts = float(last_user.get("ts") or 0)
        unanswered = assistant_ts > user_ts

        # Накопление попыток достучаться: берём счётчик последней серии
        # (последней записи в истории), т.к. Мита переформулирует вопросы —
        # текст не совпадает дословно. attempts = число попыток серии.
        unanswered_q = perception.get("unanswered_questions") or []
        attempts = int(unanswered_q[-1].get("attempts") or 1) if unanswered_q else 0

        if assistant_text and "?" in assistant_text and unanswered:
            # С ростом числа попыток меняется и характер реакции:
            # 1-я — обычный переспрос; 2+ — настойчивее; 3+ — заметно.
            stress = float(internal.get("stress", 0.05))
            if attempts >= 4:
                # Финальное состояние: много попыток без ответа. Персонаж должен
                # выбрать сценарий — обидеться / перестать спрашивать / использовать
                # инструменты / смириться. Зависит от характера (обрабатывается в
                # ReactionPolicy) и настроения (stress).
                if stress >= 0.6:
                    description = ("Персонаж много раз пытался достучаться и не получил ответа; "
                                   "он расстроен/раздражён — может обидеться или замолчать")
                else:
                    description = ("Персонаж много раз пытался достучаться и не получил ответа; "
                                   "нужно выбрать сценарий: настойчиво позвать (инструменты) или "
                                   "смириться/обидеться")
                priority = 5
            elif attempts >= 3:
                description = "Персонаж уже не раз спрашивал и не получил ответа — проявить настойчивость или обидеться"
                priority = 5
            elif attempts >= 2:
                description = "Персонаж спрашивает повторно — пользователь так и не ответил"
                priority = 4
            else:
                description = "Персонаж задал вопрос, пользователь молчит — переспросить/продолжить"
                priority = 4
            desires.append(
                {
                    "type": "respond_to_own_question",
                    "description": description,
                    # Приоритет выше фоновых событий (react_to_event=3), чтобы
                    # неотвеченный вопрос обрабатывался в первую очередь.
                    "priority": priority,
                    "source": "events",
                    "attempts": attempts,
                }
            )

        desires.sort(key=lambda m: -int(m.get("priority", 0)))
        return desires
