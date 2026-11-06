"""Decision Engine: выбор поведения на основе восприятия и мотивов.

На этапе 4 используется детерминированная эвристика (без LLM) с поддержкой
лимита инициатив (защита от зацикливания). Полноценная LLM-оценка может быть
добавлена позже, но базовая логика должна оставаться предсказуемой.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .decision_context import DecisionContext


class DecisionEngine:
    def __init__(self, *, max_initiatives_per_minute: int = 2) -> None:
        self._max_per_minute = max(1, int(max_initiatives_per_minute))
        self._initiative_times: List[float] = []

    def decide(self, ctx: DecisionContext) -> Dict[str, Any]:
        """Вернуть решение: {"action": ..., "reason": ..., "meta": ...}.

        Возможные действия:
          - "silence" — промолчать (естественное поведение)
          - "initiate_dialogue" — начать разговор
          - "act" — выполнить действие
          - "defer" — отложить (нет подходящего момента)
        """
        if not ctx.motives:
            return {"action": "silence", "reason": "no motives", "meta": {}}

        # Лимит инициатив за минуту.
        if not self._within_limit():
            return {"action": "defer", "reason": "initiative rate limit", "meta": {}}

        # Приоритетный мотив.
        top = max(ctx.motives, key=lambda m: m.get("priority", 0))
        mtype = str(top.get("type", ""))
        source = str(top.get("source", ""))

        if source == "events" and ctx.can_initiate_dialogue:
            self._record_initiative()
            return {
                "action": "initiate_dialogue",
                "reason": f"реакция на событие: {mtype}",
                "meta": {"motive": top},
            }

        if source == "window" and ctx.actions_available:
            self._record_initiative()
            return {
                "action": "act",
                "reason": f"наблюдение за окном: {mtype}",
                "meta": {"motive": top},
            }

        if source == "working_state":
            # Открытые вопросы — хороший повод заговорить, если можно.
            if ctx.can_initiate_dialogue:
                self._record_initiative()
                return {
                    "action": "initiate_dialogue",
                    "reason": "продолжить незакрытый фокус",
                    "meta": {"motive": top},
                }

        return {"action": "silence", "reason": "нет подходящего момента", "meta": {"motive": top}}

    # ------------------------------------------------------------- helpers

    def _within_limit(self) -> bool:
        now = time.time()
        cutoff = now - 60.0
        self._initiative_times = [t for t in self._initiative_times if t > cutoff]
        return len(self._initiative_times) < self._max_per_minute

    def _record_initiative(self) -> None:
        self._initiative_times.append(time.time())
