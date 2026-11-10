"""Decision Engine — Этап 5.

Выбор поведения на основе восприятия и мотивов. Decision решает, СТОИТ ли
реализовывать мотив сейчас: выбрать один мотив, отложить или отказаться.

Учитывает:
- лимит инициатив в минуту (defer при превышении);
- доступность действий (can_initiate_dialogue / actions_available);
- явный маппинг типа мотива → действие;
- предыдущие инициативы (cooldown на уровне движка).

Остаётся предсказуемым (без LLM).
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from .decision_context import DecisionContext

# Соответствие типа мотива → действие.
ACTION_BY_TYPE: Dict[str, str] = {
    "react_to_event": "initiate_dialogue",
    "continue_conversation": "initiate_dialogue",
    "ask_followup": "initiate_dialogue",
    "return_to_unfinished_topic": "initiate_dialogue",
    "want_to_interact": "initiate_dialogue",
    "share_thought": "initiate_dialogue",
    "continue_topic": "initiate_dialogue",  # мотив продолжения темы (движок)
    "respond_to_own_question": "initiate_dialogue",  # вопрос + молчание пользователя
    "comment_on_environment": "act",
}


class DecisionEngine:
    def __init__(self, *, max_initiatives_per_minute: int = 2) -> None:
        self._max_per_minute = max(1, int(max_initiatives_per_minute))
        self._initiative_times: List[float] = []

    def decide(self, ctx: DecisionContext) -> Dict[str, Any]:
        """Вернуть решение: {"action": ..., "reason": ..., "meta": ...}."""
        if not ctx.motives:
            return {"action": "silence", "reason": "no motives", "meta": {}}

        if not self._within_limit():
            return {"action": "defer", "reason": "initiative rate limit", "meta": {}}

        top = self._pick_top(ctx.motives)
        mtype = str(top.get("type", ""))
        action = ACTION_BY_TYPE.get(mtype)
        if action is None:
            # Fallback по источнику (для незнакомых мотивов).
            source = str(top.get("source", ""))
            if source == "window":
                action = "act"
            elif source in ("events", "working_state"):
                action = "initiate_dialogue"
            else:
                action = ""

        if action == "initiate_dialogue":
            if not ctx.can_initiate_dialogue:
                return {"action": "silence", "reason": "dialogue not allowed", "meta": {"motive": top}}
            self._record_initiative()
            return {
                "action": action,
                "reason": f"реакция на событие/состояние: {mtype}",
                "meta": {"motive": top},
            }

        if action == "act":
            if not ctx.actions_available:
                return {"action": "silence", "reason": "actions unavailable", "meta": {"motive": top}}
            self._record_initiative()
            return {
                "action": action,
                "reason": f"наблюдение/состояние: {mtype}",
                "meta": {"motive": top},
            }

        return {"action": "silence", "reason": "нет подходящего момента", "meta": {"motive": top}}

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _pick_top(motives: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Выбрать верхний мотив: max priority, при равенстве — первый в списке."""
        return min(
            enumerate(motives),
            key=lambda iv: (-int(iv[1].get("priority", 0)), iv[0]),
        )[1]

    def _within_limit(self) -> bool:
        now = time.time()
        cutoff = now - 60.0
        self._initiative_times = [t for t in self._initiative_times if t > cutoff]
        return len(self._initiative_times) < self._max_per_minute

    def _record_initiative(self) -> None:
        self._initiative_times.append(time.time())
