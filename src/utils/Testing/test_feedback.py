"""Тесты Этапа 7 (доработка): разделение доставки и достижения цели в Feedback."""
from __future__ import annotations

import unittest

from initiative_engine.feedback import FeedbackSystem


class FeedbackDeliveryGoalTest(unittest.TestCase):
    def setUp(self):
        self.f = FeedbackSystem()

    def test_error_yields_failed_delivery(self):
        r = self.f.process(intention={}, action_result="[ошибка] net timeout")
        self.assertEqual(r["outcome"], "failed")
        self.assertEqual(r["delivery"], "failed")
        self.assertEqual(r["action"], "retry")

    def test_delivered_dialogue_awaits_reaction(self):
        r = self.f.process(intention={}, action_result="[InitiativeAction] dialogue initiated", delivered=True)
        self.assertEqual(r["outcome"], "success")
        self.assertEqual(r["delivery"], "delivered")
        self.assertEqual(r["goal"], "pending")
        self.assertEqual(r["action"], "await_reaction")

    def test_tool_success_completes_goal(self):
        r = self.f.process(intention={}, action_result="ok")
        self.assertEqual(r["goal"], "achieved")
        self.assertEqual(r["action"], "complete")

    def test_user_reaction_achieves_goal(self):
        r = self.f.process(intention={}, action_result="x", user_reaction="привет")
        self.assertEqual(r["goal"], "achieved")
        self.assertEqual(r["action"], "complete")

    def test_user_reaction_overrides_await(self):
        r = self.f.process(
            intention={}, action_result="[InitiativeAction] dialogue initiated",
            delivered=True, user_reaction="ок",
        )
        self.assertEqual(r["action"], "complete")
        self.assertEqual(r["goal"], "achieved")

    def test_stale_cancels(self):
        r = self.f.process(intention={}, action_result="ok", event={"stale": True})
        self.assertEqual(r["outcome"], "stale")
        self.assertEqual(r["action"], "cancel")


if __name__ == "__main__":
    unittest.main()
