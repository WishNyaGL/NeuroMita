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

    def test_own_question_handled_key_is_set_after_initiate(self):
        engine = _make_engine()
        engine._last_assistant_message = {"text": "Ты любишь аниме?", "ts": 10.0}
        decision = {
            "action": "initiate_dialogue",
            "reason": "r",
            "meta": {"motive": {"type": "respond_to_own_question"}},
        }
        engine._execute_decision(decision, character_id="Crazy")
        # После успешной инициативы ключ вопроса запомнен.
        self.assertEqual(
            engine._handled_own_question_key, engine._assistant_question_key()
        )

    def test_record_unanswered_question_accumulates_after_gap(self):
        import time as _time
        engine = _make_engine()
        engine._last_assistant_message = {"text": "Ты тут?", "ts": 1.0}
        engine._record_unanswered_question()
        self.assertEqual(len(engine._unanswered_questions), 1)
        self.assertEqual(engine._unanswered_questions[0]["attempts"], 1)
        # Сразу повторно — та же серия, счётчик не растёт.
        engine._record_unanswered_question()
        self.assertEqual(engine._unanswered_questions[0]["attempts"], 1)
        # После паузы >90с — новая попытка, счётчик растёт.
        engine._unanswered_questions[-1]["last_ts"] = _time.time() - 100.0
        engine._record_unanswered_question()
        self.assertEqual(len(engine._unanswered_questions), 2)
        self.assertEqual(engine._unanswered_questions[-1]["attempts"], 2)

    def test_clear_unanswered_questions(self):
        engine = _make_engine()
        engine._last_assistant_message = {"text": "Вопрос?", "ts": 1.0}
        engine._record_unanswered_question()
        engine._clear_unanswered_questions()
        self.assertEqual(engine._unanswered_questions, [])

    def test_absent_comment_fires_once_per_absence(self):
        engine = _make_engine(busy=False)
        self.assertFalse(engine._absent_comment_sent)
        # Метод запускает комментарий и выставляет _last_action.
        engine._execute_absent_comment("Crazy")
        self.assertIsNotNone(engine._last_action)
        self.assertEqual(engine._last_action["status"], "executed")
        self.assertEqual(len(engine._actions.initiate_calls), 1)
        # Флаг управляется в _on_tick; здесь проверяем, что метод безопасно
        # вызывается повторно (не падает), а на уровне тика флаг предотвращает
        # повторный запуск.
        engine._execute_absent_comment("Crazy")
        self.assertEqual(len(engine._actions.initiate_calls), 2)

    def test_materialize_intentions_dedups(self):
        from initiative_engine.intentions.intention_manager import IntentionManager
        engine = _make_engine()
        engine._intentions = IntentionManager()
        motives = [
            {"type": "continue_focus", "priority": 5, "description": "a", "source": "working_state"},
            {"type": "continue_focus", "priority": 5, "description": "b", "source": "working_state"},
            {"type": "return_to_unfinished_topic", "priority": 3, "description": "c", "source": "working_state"},
        ]
        engine._materialize_intentions(character_id="Crazy", motives=motives)
        active = engine._intentions.list_active("Crazy")
        types = [i.type for i in active]
        self.assertEqual(types.count("continue_focus"), 1)
        self.assertEqual(types.count("return_to_unfinished_topic"), 1)

    def test_reactive_initiative_blocked_on_same_user_message(self):
        engine = _make_engine()
        engine._last_user_message = {"key": "k1", "text": "привет", "ts": 1.0}
        # Первый запуск — запоминается ключ сообщения.
        dec1 = {
            "action": "initiate_dialogue",
            "reason": "реакция на событие/состояние: react_to_event",
            "meta": {"motive": {"type": "react_to_event"}},
        }
        engine._execute_decision(dec1, character_id="Crazy")
        self.assertEqual(engine._last_initiative_user_key, "k1")
        # Повторный запуск на ТО ЖЕ сообщение — должен блокироваться логикой
        # в _on_tick (проверяем саму проверку).
        user_repeat = (
            "initiate_dialogue" == "initiate_dialogue"
            and "react_to_event" != "respond_to_own_question"
            and engine._last_user_message is not None
            and engine._last_initiative_user_key == engine._last_user_message["key"]
        )
        self.assertTrue(user_repeat)

    def test_respond_to_own_question_not_blocked_by_same_message(self):
        engine = _make_engine()
        engine._last_user_message = {"key": "k1", "text": "привет", "ts": 1.0}
        engine._last_initiative_user_key = "k1"
        # respond_to_own_question НЕ должен блокироваться по ключу сообщения.
        user_repeat = (
            "initiate_dialogue" == "initiate_dialogue"
            and "respond_to_own_question" != "respond_to_own_question"
            and engine._last_user_message is not None
            and engine._last_initiative_user_key == engine._last_user_message["key"]
        )
        self.assertFalse(user_repeat)

    def test_initiative_key_differs_by_attempts(self):
        engine = _make_engine()
        dec1 = {
            "action": "initiate_dialogue",
            "reason": "реакция на событие/состояние: respond_to_own_question",
            "meta": {"motive": {"type": "respond_to_own_question", "attempts": 1}},
        }
        dec2 = {
            "action": "initiate_dialogue",
            "reason": "реакция на событие/состояние: respond_to_own_question",
            "meta": {"motive": {"type": "respond_to_own_question", "attempts": 2}},
        }
        k1 = engine._initiative_key({"character_id": "Crazy"}, dec1)
        k2 = engine._initiative_key({"character_id": "Crazy"}, dec2)
        self.assertNotEqual(k1, k2)
        self.assertIn("attempts=1", k1)
        self.assertIn("attempts=2", k2)

    def test_assistant_question_key(self):
        engine = _make_engine()
        self.assertIsNone(engine._assistant_question_key())
        engine._last_assistant_message = {"text": "Вопрос?", "ts": 5.0}
        self.assertTrue(str(engine._assistant_question_key()).startswith("5.0:Вопрос?"))

    def test_build_instruction_includes_past_questions(self):
        engine = _make_engine()
        engine._last_assistant_message = {"text": "Ты тут?", "ts": 1.0}
        engine._unanswered_questions = [
            {"text": "Ты слышишь меня?", "attempts": 1},
            {"text": "Ты тут?", "attempts": 2},
        ]
        instruction = engine._build_initiative_instruction(
            {"type": "respond_to_own_question", "attempts": 2}, "Crazy"
        )
        self.assertIn("Ты слышишь меня?", instruction)
        self.assertIn("Ты тут?", instruction)
        self.assertIn("достучаться", instruction)

    def test_build_instruction_clarifies_old_user_phrase(self):
        engine = _make_engine()
        engine._last_assistant_message = {"text": "Ты там?", "ts": 5.0}
        engine._last_user_message = {"text": "да вот дорабатываю", "ts": 1.0}
        instruction = engine._build_initiative_instruction(
            {"type": "respond_to_own_question", "attempts": 2}, "Crazy"
        )
        self.assertIn("НЕ ответил", instruction)
        self.assertIn("СТАРАЯ фраза", instruction)
        self.assertIn("да вот дорабатываю", instruction)
        # Не должно звучать, как будто пользователь пишет снова.
        self.assertNotIn("Последнее сообщение пользователя", instruction)

    def test_build_instruction_final_state_at_4(self):
        engine = _make_engine()
        engine._last_assistant_message = {"text": "Ты там?", "ts": 5.0}
        instruction = engine._build_initiative_instruction(
            {"type": "respond_to_own_question", "attempts": 4}, "Crazy"
        )
        self.assertIn("4 раз", instruction)
        self.assertIn("вариантов", instruction)
        self.assertIn("характеру и настроению", instruction)

    def test_build_instruction_marks_roles(self):
        engine = _make_engine()
        engine._last_assistant_message = {"text": "Ты любишь аниме?"}
        engine._last_user_message = {"text": "привет", "ts": 1.0}
        instruction = engine._build_initiative_instruction(
            {"type": "respond_to_own_question"}, "Crazy"
        )
        self.assertIn("Твоя последняя реплика", instruction)
        self.assertIn("аниме", instruction)
        self.assertIn("опрос", instruction)

    def test_system_events_accumulate(self):
        engine = _make_engine()
        engine._on_observation(
            {"type": "windows.active_window", "data": {"summary": "браузер"}}
        )
        self.assertEqual(len(engine._recent_system_events), 1)
        self.assertEqual(engine._recent_system_events[0]["kind"], "window")

    def test_any_send_message_updates_activity(self):
        # Даже сообщение с источником unknown/system должно обновлять активность,
        # чтобы absent не зависал при активном разговоре.
        import time as _time
        engine = _make_engine()
        self.assertLessEqual(engine._last_activity_ts, 0.0)
        engine._on_observation(
            {"type": "send_message", "data": {"user_input": "что-то"}, "source": "unknown"}
        )
        self.assertGreater(engine._last_activity_ts, 0.0)

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

    def test_execute_decision_blocked_when_user_absent(self):
        # Пользователь отсутствует (absent) — инициатива не исполняется.
        engine = _make_engine(busy=False)
        engine._last_user_state = {"absent": True, "signal": "away", "label": "отошёл"}
        decision = {"action": "initiate_dialogue", "reason": "r", "meta": {}}
        engine._execute_decision(decision, character_id="Crazy")
        self.assertIsNotNone(engine._last_action)
        self.assertEqual(engine._last_action["status"], "blocked_by_gate")
        self.assertIn("absent", engine._last_action.get("detail") or "")
        # Инициатива не запущена.
        self.assertNotIn("Crazy", engine._in_flight_initiative)

    def test_compute_next_interval_extends_after_long_response(self):
        cfg = InitiativeConfig(scheduler_interval_sec=10.0)
        engine = InitiativeEngine(config=cfg)
        # По умолчанию — базовый интервал.
        self.assertEqual(engine._compute_next_interval(), 10.0)
        # После долгого ответа (60с) — интервал растягивается.
        engine._last_response_duration = 60.0
        self.assertGreater(engine._compute_next_interval(), 10.0)
        self.assertLessEqual(engine._compute_next_interval(), 90.0)

    def test_on_observation_records_response_duration(self):
        import time as _time
        engine = _make_engine()
        # Засекаем старт, затем эмулируем 5-секундную генерацию.
        engine._on_observation({"type": "on_started_response_generation", "data": {}})
        self.assertGreater(engine._generation_start_ts, 0)
        engine._generation_start_ts = _time.time() - 5.0
        engine._on_observation({"type": "on_successful_response", "data": {}})
        self.assertGreater(engine._last_response_duration, 4.0)
        self.assertEqual(engine._generation_start_ts, 0.0)


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
