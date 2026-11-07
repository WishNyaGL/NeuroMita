"""Тесты Этапа 3: UserInteractionState + InitiativeGate."""
from __future__ import annotations

import time
import unittest

from initiative_engine.interaction import InitiativeGate, UserInteractionState


class UserStateTest(unittest.TestCase):
    def _snap(self, text, now=None):
        state = UserInteractionState()
        return state.update(
            last_user_message={"text": text, "ts": (now or time.time()) - 10},
            now=now or time.time(),
        )

    def test_goodbye_signal(self):
        self.assertEqual(self._snap("Пока, до встречи!")["signal"], "goodbye")

    def test_sleep_signal(self):
        self.assertEqual(self._snap("Я пойду спать")["signal"], "sleep")

    def test_busy_signal(self):
        self.assertEqual(self._snap("Сейчас занят, позже")["signal"], "busy")

    def test_dnd_signal(self):
        self.assertEqual(self._snap("Не беспокоить меня")["signal"], "do_not_disturb")

    def test_return_signal(self):
        self.assertEqual(self._snap("Я вернулся")["signal"], "return")

    def test_no_signal_plain_message(self):
        self.assertEqual(self._snap("Как дела?")["signal"], None)

    def test_active_conversation_recent(self):
        now = time.time()
        snap = self._snap("Привет", now=now)
        self.assertTrue(snap["active_conversation"])

    def test_inactive_after_long_silence(self):
        now = time.time()
        state = UserInteractionState()
        snap = state.update(
            last_user_message={"text": "Привет", "ts": now - 1000},
            now=now,
        )
        self.assertFalse(snap["active_conversation"])


class GateTest(unittest.TestCase):
    def _us(self, signal):
        return {"signal": signal, "label": signal or "—"}

    def test_allows_dialogue_by_default(self):
        allowed, reason = InitiativeGate().allow("initiate_dialogue", {})
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_denies_dnd(self):
        allowed, reason = InitiativeGate().allow(
            "initiate_dialogue", self._us("do_not_disturb")
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "user_do_not_disturb")

    def test_denies_busy_user(self):
        self.assertFalse(InitiativeGate().allow("initiate_dialogue", self._us("busy"))[0])

    def test_denies_sleep(self):
        self.assertFalse(InitiativeGate().allow("initiate_dialogue", self._us("sleep"))[0])

    def test_denies_goodbye(self):
        self.assertFalse(InitiativeGate().allow("initiate_dialogue", self._us("goodbye"))[0])

    def test_denies_character_busy(self):
        allowed, reason = InitiativeGate().allow("initiate_dialogue", {}, busy=True)
        self.assertFalse(allowed)
        self.assertEqual(reason, "character_busy")

    def test_act_always_allowed(self):
        self.assertTrue(InitiativeGate().allow("act", self._us("do_not_disturb"))[0])


if __name__ == "__main__":
    unittest.main()
