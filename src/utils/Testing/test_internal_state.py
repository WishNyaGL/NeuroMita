"""Тесты Этапа 4: InternalStateAdapter."""
from __future__ import annotations

import unittest

from initiative_engine.internal_state.adapter import InternalStateAdapter


class _FakeCharacter:
    def __init__(self, stats):
        self._stats = stats

    def get_stats_dict(self):
        return dict(self._stats)


class InternalStateAdapterTest(unittest.TestCase):
    def setUp(self):
        self.adapter = InternalStateAdapter()

    def test_normalizes_stats(self):
        char = _FakeCharacter({"attitude": 75.0, "boredom": 50.0, "stress": 20.0})
        state = self.adapter.evaluate(char)
        self.assertEqual(state["attitude"], 0.75)
        self.assertEqual(state["boredom"], 0.5)
        self.assertEqual(state["stress"], 0.2)

    def test_clamps_out_of_range(self):
        char = _FakeCharacter({"attitude": 200.0, "boredom": -5.0, "stress": 0.0})
        state = self.adapter.evaluate(char)
        self.assertEqual(state["attitude"], 1.0)
        self.assertEqual(state["boredom"], 0.0)

    def test_defaults_without_character(self):
        state = self.adapter.evaluate(None)
        self.assertEqual(state["attitude"], 0.6)
        self.assertEqual(state["boredom"], 0.1)
        self.assertEqual(state["stress"], 0.05)
        self.assertEqual(state["curiosity"], 0.2)

    def test_curiosity_grows_with_activity(self):
        base = self.adapter.evaluate(None, {})["curiosity"]
        perception = {
            "events": [{"significance": 0.75}, {"significance": 0.75}],
            "open_loops": ["вопрос 1", "вопрос 2"],
            "window_context": "VS Code",
        }
        active = self.adapter.evaluate(None, perception)["curiosity"]
        self.assertGreater(active, base)
        self.assertLessEqual(active, 1.0)


if __name__ == "__main__":
    unittest.main()
