"""Тесты Этапа 2: улучшение Perception (анализ содержания)."""
from __future__ import annotations

import unittest

from initiative_engine.perception.perception_engine import PerceptionEngine


class _FakeWorkingState:
    def __init__(self, text: str):
        self._text = text

    def format_for_prompt(self):
        return self._text


class _FakeMemory:
    def __init__(self, text: str):
        self._text = text

    def get_memories_formatted(self):
        return self._text


class _FakeCharacter:
    def __init__(self, char_id="Crazy", working="", memory="", intro="Сильный и любопытный"):
        self.char_id = char_id
        self.working_state = _FakeWorkingState(working)
        self.memory_system = _FakeMemory(memory) if memory else None
        self.intro = intro


class _FakeRegistry:
    def __init__(self, char):
        self._char = char

    def get(self, character_id):
        return self._char if character_id == self._char.char_id else None


class PerceptionStage2Test(unittest.TestCase):
    def test_empty_without_character(self):
        pe = PerceptionEngine(character_registry=None)
        res = pe.perceive(character_id="Crazy", events=[{"type": "tool.search", "data": {}}])
        self.assertEqual(res["character_id"], "Crazy")
        self.assertIsNone(res["topic"])
        self.assertEqual(res["open_loops"], [])
        self.assertEqual(res["confidence"], 0.2)

    def test_event_enrichment_source_and_significance(self):
        char = _FakeCharacter(working="Обсуждаем игру.")
        pe = PerceptionEngine(character_registry=_FakeRegistry(char))
        events = [
            {"type": "tool.search", "data": {"character_id": "Crazy"}},
            {"type": "windows.active_window", "data": {"summary": "VS Code"}},
        ]
        res = pe.perceive(character_id="Crazy", events=events)
        enriched = res["events"]
        self.assertEqual(enriched[0]["source"], "tool")
        self.assertEqual(enriched[0]["significance"], 0.75)
        self.assertEqual(enriched[1]["source"], "external")
        self.assertEqual(enriched[1]["significance"], 0.55)

    def test_open_loops_detected(self):
        char = _FakeCharacter(working="Надо спросить, как прошла игра? Пока жду.")
        pe = PerceptionEngine(character_registry=_FakeRegistry(char))
        res = pe.perceive(character_id="Crazy")
        self.assertTrue(len(res["open_loops"]) >= 1)

    def test_topic_from_last_user_message(self):
        char = _FakeCharacter(working="Рабочий контекст.")
        pe = PerceptionEngine(character_registry=_FakeRegistry(char))
        res = pe.perceive(
            character_id="Crazy",
            extra_context={"last_user_message": {"text": "Расскажи про космос"}},
        )
        self.assertEqual(res["topic"], "Расскажи про космос")

    def test_confidence_rises_with_context(self):
        char = _FakeCharacter(working="Есть рабочее состояние.", memory="воспоминание о прошлом")
        pe = PerceptionEngine(character_registry=_FakeRegistry(char))
        res = pe.perceive(character_id="Crazy", events=[{"type": "tool.x", "data": {}}])
        self.assertGreater(res["confidence"], 0.3)
        self.assertLessEqual(res["confidence"], 0.95)


if __name__ == "__main__":
    unittest.main()
