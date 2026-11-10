"""Тесты Этапа 5: MotivationSystem + DecisionEngine."""
from __future__ import annotations

import time
import unittest

from initiative_engine.decision.decision_context import DecisionContext
from initiative_engine.decision.decision_engine import DecisionEngine
from initiative_engine.motivation.motivation_system import MotivationSystem


def _perception(**kw):
    base = {
        "events": [],
        "working_state": "",
        "window_context": "",
        "open_loops": [],
        "internal_state": {"boredom": 0.1, "stress": 0.05, "curiosity": 0.2},
    }
    base.update(kw)
    return base


class MotivationTest(unittest.TestCase):
    def setUp(self):
        self.m = MotivationSystem()

    def test_empty_when_nothing(self):
        self.assertEqual(self.m.evaluate(_perception()), [])

    def test_react_to_significant_event(self):
        percep = _perception(events=[{"significance": 0.75}])
        types = [d["type"] for d in self.m.evaluate(percep)]
        self.assertIn("react_to_event", types)

    def test_return_to_unfinished_on_open_loops(self):
        percep = _perception(open_loops=["вопрос?"])
        types = [d["type"] for d in self.m.evaluate(percep)]
        self.assertIn("return_to_unfinished_topic", types)

    def test_comment_on_environment_boosted_by_curiosity(self):
        percep = _perception(window_context="IDE", internal_state={"curiosity": 0.7})
        motives = self.m.evaluate(percep)
        comment = next((m for m in motives if m["type"] == "comment_on_environment"), None)
        self.assertIsNotNone(comment)
        self.assertEqual(comment["priority"], 2)

    def test_want_to_interact_when_bored(self):
        percep = _perception(internal_state={"boredom": 0.8, "stress": 0.1})
        types = [d["type"] for d in self.m.evaluate(percep)]
        self.assertIn("want_to_interact", types)

    def test_no_interact_when_stressed(self):
        percep = _perception(internal_state={"boredom": 0.8, "stress": 0.8})
        types = [d["type"] for d in self.m.evaluate(percep)]
        self.assertNotIn("want_to_interact", types)

    def test_sorted_by_priority_desc(self):
        percep = _perception(
            events=[{"significance": 0.75}],
            window_context="X",
            open_loops=["?"],
        )
        motives = self.m.evaluate(percep)
        prios = [int(m["priority"]) for m in motives]
        self.assertEqual(prios, sorted(prios, reverse=True))

    def test_respond_to_own_question_motive(self):
        # Персонаж задал вопрос, пользователь НЕ отвечал (ts пользователя < ts вопроса)
        # — должен появиться мотив переспросить/продолжить.
        percep = _perception(
            last_assistant_message={"text": "Ты любишь аниме?", "ts": 10.0},
            last_user_message={"text": "привет", "ts": 1.0},
        )
        types = [d["type"] for d in self.m.evaluate(percep)]
        self.assertIn("respond_to_own_question", types)

    def test_no_respond_motive_when_question_answered(self):
        # Пользователь ответил ПОСЛЕ вопроса — мотива нет (не переспрашиваем).
        percep = _perception(
            last_assistant_message={"text": "Ты любишь аниме?", "ts": 5.0},
            last_user_message={"text": "да, люблю", "ts": 10.0},
        )
        types = [d["type"] for d in self.m.evaluate(percep)]
        self.assertNotIn("respond_to_own_question", types)

    def test_no_respond_motive_without_question(self):
        percep = _perception(
            last_assistant_message={"text": "Это интересная тема.", "ts": 1.0}
        )
        types = [d["type"] for d in self.m.evaluate(percep)]
        self.assertNotIn("respond_to_own_question", types)

    def test_attempts_reflected_in_motive(self):
        # 3 попытки в последней серии — приоритет и описание меняются.
        percep = _perception(
            last_assistant_message={"text": "Ты тут?", "ts": 10.0},
            last_user_message={"text": "привет", "ts": 1.0},
            unanswered_questions=[{"text": "Какой-то вопрос", "attempts": 3}],
        )
        motives = self.m.evaluate(percep)
        q = next(m for m in motives if m["type"] == "respond_to_own_question")
        self.assertEqual(q["attempts"], 3)
        self.assertEqual(q["priority"], 5)

    def test_final_state_at_4_attempts(self):
        percep = _perception(
            last_assistant_message={"text": "Ты там?", "ts": 10.0},
            last_user_message={"text": "привет", "ts": 1.0},
            unanswered_questions=[{"text": "q", "attempts": 4}],
            internal_state={"stress": 0.2},
        )
        motives = self.m.evaluate(percep)
        q = next(m for m in motives if m["type"] == "respond_to_own_question")
        self.assertEqual(q["attempts"], 4)
        self.assertEqual(q["priority"], 5)
        self.assertIn("сценарий", q["description"])

    def test_own_question_priority_above_react_to_event(self):
        # Неотвеченный вопрос должен иметь приоритет выше фоновых событий.
        percep = _perception(
            events=[{"significance": 0.75}],
            last_assistant_message={"text": "Ты любишь аниме?", "ts": 10.0},
            last_user_message={"text": "привет", "ts": 1.0},
        )
        motives = self.m.evaluate(percep)
        by_type = {m["type"]: m for m in motives}
        self.assertIn("respond_to_own_question", by_type)
        self.assertIn("react_to_event", by_type)
        self.assertGreater(
            by_type["respond_to_own_question"]["priority"],
            by_type["react_to_event"]["priority"],
        )


class DecisionTest(unittest.TestCase):
    def _ctx(self, motives, can=True, actions=True, max_per_min=2):
        eng = DecisionEngine(max_initiatives_per_minute=max_per_min)
        ctx = DecisionContext(
            character_id="Crazy",
            perception={},
            motives=motives,
            can_initiate_dialogue=can,
            actions_available=actions,
        )
        return eng, ctx

    def test_comment_maps_to_act(self):
        eng, ctx = self._ctx([{"type": "comment_on_environment", "priority": 2, "source": "window"}])
        self.assertEqual(eng.decide(ctx)["action"], "act")

    def test_react_maps_to_initiate(self):
        eng, ctx = self._ctx([{"type": "react_to_event", "priority": 3, "source": "events"}])
        self.assertEqual(eng.decide(ctx)["action"], "initiate_dialogue")

    def test_respond_to_own_question_maps_to_initiate(self):
        eng, ctx = self._ctx(
            [{"type": "respond_to_own_question", "priority": 2, "source": "events"}]
        )
        self.assertEqual(eng.decide(ctx)["action"], "initiate_dialogue")

    def test_initiate_blocked_when_not_allowed(self):
        eng, ctx = self._ctx(
            [{"type": "react_to_event", "priority": 3, "source": "events"}], can=False
        )
        self.assertEqual(eng.decide(ctx)["action"], "silence")

    def test_act_blocked_when_no_actions(self):
        eng, ctx = self._ctx(
            [{"type": "comment_on_environment", "priority": 2, "source": "window"}], actions=False
        )
        self.assertEqual(eng.decide(ctx)["action"], "silence")

    def test_no_motives_silence(self):
        eng, ctx = self._ctx([])
        self.assertEqual(eng.decide(ctx)["action"], "silence")

    def test_rate_limit_defer(self):
        eng, ctx = self._ctx(
            [{"type": "react_to_event", "priority": 3, "source": "events"}], max_per_min=1
        )
        eng._initiative_times = [time.time() - 1.0]
        self.assertEqual(eng.decide(ctx)["action"], "defer")

    def test_unknown_type_fallback_by_source(self):
        eng, ctx = self._ctx([{"type": "custom_motive", "priority": 2, "source": "window"}])
        self.assertEqual(eng.decide(ctx)["action"], "act")

    def test_tie_break_keeps_first(self):
        eng, ctx = self._ctx(
            [
                {"type": "want_to_interact", "priority": 3, "source": "working_state"},
                {"type": "react_to_event", "priority": 3, "source": "events"},
            ]
        )
        dec = eng.decide(ctx)
        self.assertEqual(dec["meta"]["motive"]["type"], "want_to_interact")


if __name__ == "__main__":
    unittest.main()
