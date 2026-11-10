"""Восприятие ситуации (PerceptionEngine) — Этап 2.

Объединяет события наблюдения, Working State, релевантные воспоминания, личность
персонажа и наблюдение за окном в структурированное понимание текущей ситуации.

На Этапе 2 добавлен лёгкий анализ содержания (без LLM):
- обогащение событий признаком значимости (significance) и источником;
- выделение текущей темы (topic) из контекста;
- детекция открытых вопросов/незакрытых фокусов (open_loops);
- краткая сводка (summary) и пересчитанная уверенность (confidence).

Всё детерминировано и не требует внешних NLP-зависимостей.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

from main_logger import logger

from ..observation.source import normalize_source

# Ключевые слова, указывающие на незакрытый вопрос/фокус.
_OPEN_LOOP_KEYWORDS = (
    "спросить",
    "узнать",
    "напомнить",
    "проверить",
    "почему",
    "какой",
    "какая",
    "какие",
    "как",
    "когда",
    "где",
    "что если",
    "надо посмотреть",
    "вопрос",
    "после",
    "позже",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


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
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Собрать понимание ситуации для заданного персонажа.

        Возвращает словарь:
          - character_id
          - personality: краткая сводка личности
          - working_state: оперативный контекст
          - memories: релевантные воспоминания
          - events: значимые события (обогащены source/significance)
          - window_context: наблюдение за Windows
          - confidence: степень уверенности (0..1)
          - topic: текущая тема (или None)
          - open_loops: список незакрытых вопросов/фокусов
          - summary: краткая текстовая сводка
          - analyzed_at: время анализа
        """
        events = events or []
        character = self._get_character(character_id)
        if character is None:
            return self._empty(character_id, events, window_context)

        working_state = ""
        try:
            working_state = character.working_state.format_for_prompt()
        except Exception:
            working_state = ""

        personality = self._personality_of(character)
        memories = self._memories_of(character, events)
        enriched = [self._enrich_event(ev) for ev in events]
        context_text = self._build_context_text(
            working_state, memories, enriched, window_context, extra_context
        )
        topic = self._extract_topic(context_text, extra_context)
        open_loops = self._detect_open_loops(working_state, context_text)
        summary = self._summarize(enriched, working_state, topic, open_loops, window_context)
        confidence = self._confidence(enriched, working_state, memories, open_loops)

        return {
            "character_id": character.char_id,
            "personality": personality,
            "working_state": working_state,
            "memories": memories,
            "events": enriched,
            "window_context": window_context or "",
            "confidence": confidence,
            "topic": topic,
            "open_loops": open_loops,
            "summary": summary,
            "analyzed_at": time.time(),
            "last_assistant_message": (extra_context or {}).get("last_assistant_message"),
            "last_user_message": (extra_context or {}).get("last_user_message"),
            "system_events": list((extra_context or {}).get("system_events") or []),
            "unanswered_questions": list(
                (extra_context or {}).get("unanswered_questions") or []
            ),
        }

    # ------------------------------------------------------------ enrichment

    @staticmethod
    def _enrich_event(event: Dict[str, Any]) -> Dict[str, Any]:
        """Добавить источнику/значимость, если их нет."""
        enriched = dict(event)
        data = enriched.get("data") or {}
        etype = str(enriched.get("type") or "")
        if not enriched.get("source"):
            enriched["source"] = normalize_source(etype, data).value
        # Значимость: инструменты и окна важнее фоновых событий.
        if etype.startswith("tool."):
            sig = 0.75
        elif etype == "windows.active_window":
            sig = 0.55
        else:
            sig = 0.4
        enriched["significance"] = sig
        return enriched

    @staticmethod
    def _build_context_text(
        working_state: str,
        memories: List[str],
        events: List[Dict[str, Any]],
        window_context: str,
        extra_context: Optional[Dict[str, Any]],
    ) -> str:
        parts: List[str] = []
        if working_state:
            parts.append(working_state)
        for m in memories:
            if m:
                parts.append(str(m))
        for ev in events:
            data = ev.get("data") or {}
            chunk = (
                data.get("summary")
                or data.get("tool_name")
                or data.get("text")
                or data.get("user_input")
                or ""
            )
            if isinstance(chunk, str) and chunk.strip():
                parts.append(chunk.strip()[:200])
        if window_context:
            parts.append(window_context)
        if extra_context:
            last_user = (extra_context.get("last_user_message") or {}).get("text")
            if last_user:
                parts.append(str(last_user))
            last_assistant = (extra_context.get("last_assistant_message") or {}).get("text")
            if last_assistant:
                parts.append(str(last_assistant))
            for sev in extra_context.get("system_events") or []:
                desc = str(sev.get("description") or "").strip()
                if desc:
                    parts.append(desc)
        return " ".join(p for p in parts if p)

    @staticmethod
    def _extract_topic(
        context_text: str, extra_context: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        # Приоритет: последнее сообщение пользователя → заметная тема из контекста.
        if extra_context:
            last_user = (extra_context.get("last_user_message") or {}).get("text")
            if isinstance(last_user, str) and last_user.strip():
                return last_user.strip()[:120]
        text = context_text.strip()
        if not text:
            return None
        sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
        for sent in sentences:
            if len(sent.split()) >= 3:
                return sent[:120]
        return text[:120]

    @staticmethod
    def _detect_open_loops(working_state: str, context_text: str) -> List[str]:
        loops: List[str] = []
        seen = set()
        for segment in (working_state, context_text):
            if not segment:
                continue
            for sent in _SENTENCE_SPLIT.split(segment):
                s = sent.strip()
                if not s or len(s) < 6 or s in seen:
                    continue
                lower = s.lower()
                if "?" in s or any(k in lower for k in _OPEN_LOOP_KEYWORDS):
                    seen.add(s)
                    loops.append(s[:160])
                    if len(loops) >= 5:
                        return loops
        return loops

    @staticmethod
    def _summarize(
        events: List[Dict[str, Any]],
        working_state: str,
        topic: Optional[str],
        open_loops: List[str],
        window_context: str,
    ) -> str:
        bits: List[str] = []
        if events:
            bits.append(f"событий: {len(events)}")
        if topic:
            bits.append(f"тема: {topic[:80]}")
        if open_loops:
            bits.append(f"открытых вопросов: {len(open_loops)}")
        if working_state:
            bits.append("есть working state")
        if window_context:
            bits.append("есть наблюдение за окном")
        return "; ".join(bits) if bits else "ничего значимого"

    @staticmethod
    def _confidence(
        events: List[Dict[str, Any]],
        working_state: str,
        memories: List[str],
        open_loops: List[str],
    ) -> float:
        base = 0.3
        significant = sum(1 for e in events if e.get("significance", 0) >= 0.5)
        base += min(0.3, significant * 0.1)
        if working_state:
            base += 0.15
        if memories:
            base += 0.1
        if open_loops:
            base += 0.1
        return round(min(0.95, base), 2)

    # ------------------------------------------------------------ internals

    def _get_character(self, character_id: Optional[str]):
        if self._registry is None or not character_id:
            return None
        try:
            return self._registry.get(character_id)
        except Exception:
            return None

    @staticmethod
    def _empty(
        character_id: Optional[str],
        events: List[Dict[str, Any]],
        window_context: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "character_id": character_id or "",
            "personality": "",
            "working_state": "",
            "memories": [],
            "events": events,
            "window_context": window_context or "",
            "confidence": 0.2,
            "topic": None,
            "open_loops": [],
            "summary": "",
            "analyzed_at": time.time(),
        }

    @staticmethod
    def _personality_of(character) -> str:
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
