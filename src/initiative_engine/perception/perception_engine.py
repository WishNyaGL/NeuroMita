"""Восприятие ситуации (PerceptionEngine).

Объединяет события наблюдения, Working State, релевантные воспоминания, личность
персонажа и (позже) анализ экрана в структурированное понимание текущей
ситуации: подтверждённые факты, предположения, значимость.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from main_logger import logger


class PerceptionEngine:
    def __init__(self, character_registry: Any = None) -> None:
        self._registry = character_registry

    # ------------------------------------------------------------ public API

    def perceive(
        self,
        *,
        character_id: Optional[str],
        events: List[Dict[str, Any]] = None,
        window_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Собрать понимание ситуации для заданного персонажа.

        Возвращает словарь:
          - character_id
          - personality: краткая сводка личности (из промптов, если доступно)
          - working_state: оперативный контекст
          - memories: релевантные воспоминания
          - events: значимые события
          - window_context: наблюдение за Windows (опционально)
          - confidence: степень уверенности (0..1)
        """
        events = events or []
        character = self._get_character(character_id)
        if character is None:
            return {
                "character_id": character_id or "",
                "personality": "",
                "working_state": "",
                "memories": [],
                "events": events,
                "window_context": window_context or "",
                "confidence": 0.2,
            }

        working_state = ""
        try:
            working_state = character.working_state.format_for_prompt()
        except Exception:
            working_state = ""

        personality = self._personality_of(character)
        memories = self._memories_of(character, events)

        return {
            "character_id": character.char_id,
            "personality": personality,
            "working_state": working_state,
            "memories": memories,
            "events": events,
            "window_context": window_context or "",
            "confidence": 0.6 if (events or working_state or memories) else 0.3,
        }

    # ------------------------------------------------------------ internals

    def _get_character(self, character_id: Optional[str]):
        if self._registry is None or not character_id:
            return None
        try:
            return self._registry.get(character_id)
        except Exception:
            return None

    @staticmethod
    def _personality_of(character) -> str:
        # Личность живёт в промптах. Берём заголовок основного шаблона (если есть).
        try:
            intro = getattr(character, "intro", "") or ""
            if isinstance(intro, str) and intro.strip():
                return intro.strip()[:300]
        except Exception:
            pass
        return ""

    @staticmethod
    def _memories_of(character, events: List[Dict[str, Any]]) -> List[str]:
        try:
            memory = character.memory_system
            if memory is None:
                return []
            formatted = memory.get_memories_formatted() or ""
            if isinstance(formatted, str) and formatted.strip():
                return [formatted.strip()[:1500]]
            return []
        except Exception:
            return []
