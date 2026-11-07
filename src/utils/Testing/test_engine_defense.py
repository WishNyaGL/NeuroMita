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

    def test_unknown_is_not_user_activity(self):
        # Неизвестный источник НЕ становится пользовательской активностью.
        engine = _make_engine()
        engine._last_user_message = {"key": "old", "text": "old", "ts": 0.0, "source": "x"}
        engine._on_observation(
            {"type": "send_message", "data": {"user_input": "текст"}, "source": "unknown"}
        )
        self.assertEqual(engine._last_user_message["text"], "old")

    def test_system_is_not_user_activity(self):
        engine = _make_engine()
        engine._last_user_message = {"key": "old", "text": "old", "ts": 0.0, "source": "x"}
        engine._on_observation(
            {"type": "send_message", "data": {"user_input": "[Системное] текст"}, "source": "system"}
        )
        self.assertEqual(engine._last_user_message["text"], "old")

    def test_empty_text_does_not_update_context(self):
        engine = _make_engine()
        engine._last_user_message = {"key": "old", "text": "old", "ts": 0.0, "source": "x"}
        engine._on_observation(
            {"type": "send_message", "data": {"user_input": " "}, "source": "player"}
        )
        self.assertEqual(engine._last_user_message["text"], "old")

    def test_player_reaction_completes_executing_intention(self):
        from initiative_engine.intentions.intention_manager import IntentionManager
        engine = _make_engine()
        engine._intentions = IntentionManager()
        it = engine._intentions.create(
            character_id="Crazy", type="react_to_event", description="d", priority=3
        )
        engine._intentions.set_status(it.id, "executing")
        engine._on_observation(
            {"type": "send_message", "data": {"user_input": "я тут"}, "source": "player"}
        )
        # После реакции намерение завершено и удалено из активного хранилища.
        self.assertEqual(engine._intentions.list_active(), [])


class MonitorDataTest(unittest.TestCase):
    def test_last_action_recorded_on_execute(self):
        engine = _make_engine(busy=False)
        decision = {"action": "initiate_dialogue", "reason": "r", "meta": {}}
        engine._execute_decision(decision, character_id="Crazy")
        self.assertIsNotNone(engine._last_action)
        self.assertEqual(engine._last_action["action"], "initiate_dialogue")
        self.assertEqual(engine._last_action["status"], "executed")

    def test_last_action_deferred_when_busy(self):
        engine = _make_engine(busy=True)
        decision = {"action": "initiate_dialogue", "reason": "r", "meta": {}}
        engine._execute_decision(decision, character_id="Crazy")
        self.assertEqual(engine._last_action["status"], "deferred_by_busy")

    def test_stats_exposes_monitor_fields(self):
        engine = _make_engine()
        # Последний цикл ещё не выполнялся — поля пустые, но присутствуют.
        stats = engine.stats()
        self.assertIn("last_motives", stats)
        self.assertIn("last_events", stats)
        self.assertIn("last_action", stats)
        self.assertIn("internal_state", stats)
        self.assertIn("intentions", stats)
        self.assertIn("in_flight_initiative", stats)
        self.assertEqual(stats["internal_state"], {})
        # Заполняем и проверяем pass-through.
        engine._last_motives = [{"type": "react_to_event", "priority": 3, "source": "events"}]
        engine._last_events = [{"type": "tool.search", "source": "tool"}]
        engine._internal_state = {"любопытство": 0.4}
        stats2 = engine.stats()
        self.assertEqual(len(stats2["last_motives"]), 1)
        self.assertEqual(stats2["last_events"][0]["type"], "tool.search")
        self.assertEqual(stats2["internal_state"]["любопытство"], 0.4)


if __name__ == "__main__":
    unittest.main()
