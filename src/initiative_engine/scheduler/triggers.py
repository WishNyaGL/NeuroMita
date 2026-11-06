"""Триггеры планировщика: условия, при которых намерение/оценка активируется.

На этапе 1 — минимальные предикаты; полноценные условия намерений добавятся
на этапе 5 (система намерений).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

TriggerFn = Callable[[Dict[str, Any]], bool]


def and_all(triggers: List[TriggerFn]) -> TriggerFn:
    def check(ctx: Dict[str, Any]) -> bool:
        return all(t(ctx) for t in triggers)

    return check


def or_any(triggers: List[TriggerFn]) -> TriggerFn:
    def check(ctx: Dict[str, Any]) -> bool:
        return any(t(ctx) for t in triggers)

    return check


def every_n_ticks(n: int) -> TriggerFn:
    counter = {"i": 0}

    def check(ctx: Dict[str, Any]) -> bool:
        counter["i"] += 1
        return counter["i"] % max(1, n) == 0

    return check
