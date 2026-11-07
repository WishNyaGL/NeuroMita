"""Тесты Этапа 6: IntentionManager (условия, ready, релевантность)."""
from __future__ import annotations

import time
import unittest

from initiative_engine.engine import InitiativeEngine
from initiative_engine.intentions.intention_manager import IntentionManager


class IntentionManagerStage6Test(unittest.TestCase):
    def setUp(self):
        self.mgr = IntentionManager()

    def test_evaluate_conditions_need_topic(self):
        it = self.mgr.create(
            character_id="Crazy",
            type="return_to_unfinished_topic",
            description="спросить про игру",
            priority=3,
            conditions={"need_topic_in": ["игра"]},
        )
        self.assertFalse(self.mgr.evaluate_conditions(it, context="говорим о погоде"))
        self.assertTrue(self.mgr.evaluate_conditions(it, context="поговорим про игру"))

    def test_evaluate_conditions_after_ts(self):
        it = self.mgr.create(
            character_id="Crazy",
            type="x",
            description="x",
            conditions={"after_ts": time.time() + 100},
        )
        self.assertFalse(self.mgr.evaluate_conditions(it))

    def test_mark_ready_transitions(self):
        self.mgr.create(
            character_id="Crazy",
            type="ask_followup",
            description="про игру",
            conditions={"need_topic_in": ["игра"]},
        )
        self.assertEqual(self.mgr.mark_ready(character_id="Crazy", context="про погоду"), 0)
        self.assertEqual(self.mgr.mark_ready(character_id="Crazy", context="про игру"), 1)
        actives = self.mgr.list_active("Crazy")
        self.assertEqual(actives[0].status, "ready")

    def test_promote_by_relevance(self):
        self.mgr.create(
            character_id="Crazy", type="topic", description="про космос", priority=2
        )
        self.mgr.create(
            character_id="Crazy", type="other", description="про еду", priority=2
        )
        promoted = self.mgr.promote_by_relevance(["космос"])
        self.assertEqual(promoted, 1)
        for it in self.mgr.list_active("Crazy"):
            if it.type == "topic":
                self.assertGreater(it.priority, 2)


class EngineKeywordHelperTest(unittest.TestCase):
    def test_keywords_from_text(self):
        kw = InitiativeEngine._keywords_from_text("Надо спросить про космос и игру")
        self.assertIn("космос", kw)
        self.assertIn("спросить", kw)
        self.assertNotIn("и", kw)


if __name__ == "__main__":
    unittest.main()
