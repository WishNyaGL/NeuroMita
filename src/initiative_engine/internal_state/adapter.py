"""Internal State Adapter — Этап 4.

Связывает автономное поведение с реальным внутренним состоянием NeuroMita:
читает числовые переменные персонажа (`attitude`, `boredom`, `stress` через
`character.get_stats_dict()`), нормализует их в диапазон [0,1] и добавляет
производный индекс любопытства (curiosity) на основе активности наблюдения.

Принципы:
- не создаёт дублирующих переменных — только читает существующие;
- любопытство — производный индекс (не хранится), отражает тягу к исследованию
  на основе значимых событий, открытых вопросов и наблюдения за окном;
- результат попадает в `perception["internal_state"]` и в `engine.stats()`,
  а также может влиять на мотивы (Этап 5).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# Диапазоны исходных переменных (для нормализации в [0,1]).
_ATTITUDE_RANGE = (0.0, 100.0)
_BOREDOM_RANGE = (0.0, 100.0)
_STRESS_RANGE = (0.0, 100.0)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


class InternalStateAdapter:
    def __init__(self) -> None:
        pass

    def evaluate(
        self,
        character: Any,
        perception: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """Вернуть нормализованное числовое состояние персонажа."""
        raw: Dict[str, float] = {}
        if character is not None:
            try:
                stats = character.get_stats_dict()
                if isinstance(stats, dict):
                    raw = stats
            except Exception:
                raw = {}

        attitude = _clamp01(_norm(raw.get("attitude", 60.0), _ATTITUDE_RANGE))
        boredom = _clamp01(_norm(raw.get("boredom", 10.0), _BOREDOM_RANGE))
        stress = _clamp01(_norm(raw.get("stress", 5.0), _STRESS_RANGE))
        curiosity = self._curiosity(perception)

        return {
            "attitude": round(attitude, 2),
            "boredom": round(boredom, 2),
            "stress": round(stress, 2),
            "curiosity": round(curiosity, 2),
        }

    # ------------------------------------------------------------- derived

    @staticmethod
    def _curiosity(perception: Optional[Dict[str, Any]]) -> float:
        """Производный индекс любопытства (0..1) из активности наблюдения."""
        perception = perception or {}
        events = perception.get("events") or []
        significant = sum(1 for e in events if e.get("significance", 0) >= 0.5)
        open_loops = perception.get("open_loops") or []
        window = bool(perception.get("window_context"))

        score = 0.2
        score += min(0.3, significant * 0.15)
        score += min(0.3, len(open_loops) * 0.1)
        if window:
            score += 0.1
        return _clamp01(score)


def _norm(value: Any, rng: Any) -> float:
    """Привести значение к [0,1] по диапазону rng=(lo, hi)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = rng[0]
    lo, hi = rng[0], rng[1]
    span = hi - lo
    if span <= 0:
        return 0.0
    return (v - lo) / span
