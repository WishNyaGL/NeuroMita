"""Тесты Изменений 2–4 (Этап 1): занятость, in-flight инициатива, источник контекста."""
from __future__ import annotations

import unittest

from initiative_engine.config import InitiativeConfig
from initiative_engine.engine import InitiativeEngine


class _FakeActions:
    def __init__(self):
        self.initiate_calls = []
        self.tool_calls = []

    def initiate_dialogue(self, character_id: str, instruction: str) -> bool:
        self.initiate_calls.append((character_id, instruction))
        return True

    def execute_tool(self, character_id: str, tool: str, args: dict) -> str:
        self.tool_calls.append((character_id, tool))
        return "ok"


class _FakeActivity:
    def __init__(self, busy: bool):
        self._busy = busy

    def active_generation_count(self, character_id=None) -> int:
        return 1 if self._busy else 0


def _make_engine(busy: bool = False) -> InitiativeEngine:
    cfg = InitiativeConfig(
        enabled=True,
        autonomy_level="full",
        respect_busy_character=True,
        allow_initiate_dialogue=True,
    )
    engine = InitiativeEngine(config=cfg)
    engine._actions = _FakeActions()
    engine._activity_service = _FakeActivity(busy)
    return engine


class BusyDeferTest(unittest.TestCase):
    def test_initiate_deferred_when_busy(self):
        engine = _make_engine(busy=True)
        decision = {
            "action": "initiate_dialogue",
            "reason": "реакция на событие: react_to_event",
            "meta": {},
        }
        engine._execute_decision(decision, character_id="Crazy")
        self.assertEqual(engine._actions.initiate_calls, [])
        self.assertNotIn("Crazy", engine._in_flight_initiative)

    def test_tool_deferred_when_busy(self):
        engine = _make_engine(busy=True)
        decision = {"action": "act", "reason": "x", "meta": {"motive": {"type": "comment_on_window"}}}
        engine._execute_decision(decision, character_id="Crazy")
        self.assertEqual(engine._actions.tool_calls, [])

    def test_initiate_allowed_when_not_busy(self):
        engine = _make_engine(busy=False)
        decision = {"action": "initiate_dialogue", "reason": "r", "meta": {}}
        engine._execute_decision(decision, character_id="Crazy")
        self.assertEqual(len(engine._actions.initiate_calls), 1)
        self.assertIn("Crazy", engine._in_flight_initiative)


class ContextSourceTest(unittest.TestCase):
    def test_context_records_source(self):
        engine = _make_engine()
        engine._on_observation(
            {"type": "send_message", "data": {"user_input": "привет"}, "source": "player"}
        )
        self.assertIsNotNone(engine._last_user_message)
        self.assertEqual(
            engine._last_user_message["source"], "player"
        )

    def test_context_records_unknown_source(self):
        # unknown НЕ становится player, но контекст как хранилище сохраняется.
        engine = _make_engine()
        engine._on_observation(
            {"type": "send_message", "data": {"user_input": "текст"}, "source": "unknown"}
        )
        self.assertEqual(engine._last_user_message["source"], "unknown")

    def test_empty_text_does_not_update_context(self):
        engine = _make_engine()
        engine._last_user_message = {"key": "old", "text": "old", "ts": 0.0, "source": "x"}
        engine._on_observation(
            {"type": "send_message", "data": {"user_input": " "}, "source": "unknown"}
        )
        self.assertEqual(engine._last_user_message["text"], "old")


if __name__ == "__main__":
    unittest.main()
