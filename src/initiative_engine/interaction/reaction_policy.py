"""Reaction Policy — Этап 7.

Определяет, как персонаж реагирует на сигналы пользователя (goodbye / sleep /
busy / do_not_disturb / return) В ЗАВИСИМОСТИ от характера и текущего состояния.

Характер извлекается из текста личности персонажа (perception["personality"])
лёгкими эвристиками по ключевым словам — по осям:
- obedience      — послушание / уважение границ;
- persistence    — настойчивость / цепкость;
- touchiness     — обидчивость;
- formality      — серьёзность / сдержанность.

Текущее состояние — internal_state (boredom, stress, attitude). Результат —
решение: уважить сигнал (respect, заблокировать инициативу) либо переопределить
(override: не послушаться, просить остаться, обидеться и т.п.).
"""
from __future__ import annotations

from typing import Any, Dict

# Ключевые слова осей характера.
_OBEDIENCE_KEYS = (
    "послушн", "вежлив", "уважает", "уважаю", "тактич", "спокойн", "сдержан"
)
_PERSISTENCE_KEYS = (
    "упрям", "настойчив", "навязчив", "цепко", "своенрав", "не отстаю",
    "не отстает", "напорист", "экспрессив"
)
_TOUCHINESS_KEYS = (
    "обидчив", "раним", "эмоциональн", "капризн", "раздраж", "вспыльчив"
)
_FORMALITY_KEYS = (
    "серьёзн", "строг", "официал", "формальн", "собранн", "дисциплинирован"
)


class TraitsProfile:
    """Профиль характера (нормализованные оси 0..1)."""

    @staticmethod
    def from_personality(personality: Any) -> Dict[str, float]:
        text = str(personality or "").lower()
        if not text.strip():
            # Нейтральный профиль по умолчанию.
            return {"obedience": 0.5, "persistence": 0.3, "touchiness": 0.3, "formality": 0.5}

        def score(keys):
            hits = sum(1 for k in keys if k in text)
            return round(min(1.0, hits / 2), 2)

        return {
            "obedience": score(_OBEDIENCE_KEYS),
            "persistence": score(_PERSISTENCE_KEYS),
            "touchiness": score(_TOUCHINESS_KEYS),
            "formality": score(_FORMALITY_KEYS),
        }


class ReactionPolicy:
    """Выбор поведения по сигналу с учётом характера и состояния."""

    @staticmethod
    def evaluate(
        signal: str,
        internal: Dict[str, Any],
        traits: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Вернуть {respect, reaction, reason}."""
        if signal == "return":
            return {"respect": False, "reaction": "welcome", "reason": "рад возвращению"}

        obedience = float(traits.get("obedience", 0.5))
        persistence = float(traits.get("persistence", 0.3))
        touchiness = float(traits.get("touchiness", 0.3))
        formality = float(traits.get("formality", 0.5))
        boredom = float(internal.get("boredom", 0.1))
        stress = float(internal.get("stress", 0.05))

        # Склонность уважить границу.
        respect = 0.4 + 0.4 * obedience + 0.2 * formality - 0.25 * persistence
        # Склонность переопределить (не послушаться / настаивать).
        override = 0.35 * persistence + 0.3 * boredom - 0.2 * stress

        if signal == "goodbye":
            # Раздельные скоры поведения: просить остаться / обидеться / уважить.
            insist = 0.45 * persistence + 0.15 * touchiness + 0.15 * boredom
            offended = 0.4 * touchiness + 0.3 * (1 - obedience)
            respect_g = 0.5 * obedience + 0.3 * formality + 0.2 * (1 - persistence)
            best = max(insist, offended, respect_g)
            if best == respect_g:
                return {"respect": True, "reaction": "respect_goodbye", "reason": "уважает прощание"}
            if best == offended:
                return {"respect": False, "reaction": "offended", "reason": "обиделся на прощание"}
            return {"respect": False, "reaction": "insist_stay", "reason": "просит остаться"}

        if signal == "do_not_disturb":
            # «Не беспокоить» — сильная граница: нарушается только персонажем с
            # выраженной настойчивостью (persistence >= 0.6) при перевесе
            # настойчивости над уважением. Иначе — уважение.
            if persistence >= 0.6 and override >= respect:
                return {"respect": False, "reaction": "ignore_dnd", "reason": "не слушается просьбы не беспокоить"}
            return {"respect": True, "reaction": "respect_dnd", "reason": "уважает «не беспокоить»"}

        if signal == "busy":
            if override >= respect:
                return {"respect": False, "reaction": "insist_now", "reason": "настаивает несмотря на занятость"}
            return {"respect": True, "reaction": "respect_busy", "reason": "уважает занятость"}

        if signal == "sleep":
            if override >= respect + 0.2:
                return {"respect": False, "reaction": "insist_stay", "reason": "не отпускает перед сном"}
            return {"respect": True, "reaction": "respect_sleep", "reason": "уважает желание спать"}

        # Неизвестный сигнал → не блокируем.
        return {"respect": False, "reaction": "neutral", "reason": ""}
