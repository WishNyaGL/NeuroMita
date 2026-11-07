"""Тесты Этапа 3: UserInteractionState + InitiativeGate."""
from __future__ import annotations

import time
import unittest

from initiative_engine.interaction import (
    InitiativeGate,
    ReactionPolicy,
    TraitsProfile,
    UserInteractionState,
)


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

    def test_away_signal(self):
        self.assertEqual(self._snap("Я отойду на минутку")["signal"], "away")

    def test_absent_when_explicit_away(self):
        self.assertTrue(self._snap("Я отойду")["absent"])

    def test_absent_after_long_inactivity(self):
        now = time.time()
        state = UserInteractionState()
        snap = state.update(
            last_user_message={"text": "Привет", "ts": now - 600},
            now=now,
        )
        self.assertTrue(snap["absent"])
        self.assertFalse(snap["active_conversation"])

    def test_not_absent_recent_activity(self):
        now = time.time()
        state = UserInteractionState()
        snap = state.update(
            last_user_message={"text": "Привет", "ts": now - 10},
            now=now,
        )
        self.assertFalse(snap["absent"])

    def test_not_absent_on_first_run_without_activity(self):
        now = time.time()
        state = UserInteractionState()
        snap = state.update(last_user_message=None, now=now)
        self.assertFalse(snap["absent"])

    def test_absent_cleared_on_new_message(self):
        now = time.time()
        state = UserInteractionState()
        state.update(last_user_message={"text": "Пока", "ts": now - 600}, now=now)
        self.assertTrue(state.update(
            last_user_message={"text": "Я тут", "ts": now}, now=now
        )["absent"] is False)

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
        self.assertTrue(reason.startswith("user_do_not_disturb"))

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

    def test_absent_denies_dialogue(self):
        allowed, reason = InitiativeGate().allow(
            "initiate_dialogue", {"absent": True, "signal": "away"}
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "user_absent")


class TraitsProfileTest(unittest.TestCase):
    def test_neutral_defaults(self):
        t = TraitsProfile.from_personality("")
        self.assertEqual(t["obedience"], 0.5)
        self.assertEqual(t["persistence"], 0.3)

    def test_detects_persistence(self):
        t = TraitsProfile.from_personality("Упрямый и настойчивый персонаж")
        self.assertGreater(t["persistence"], 0.3)

    def test_detects_obedience(self):
        t = TraitsProfile.from_personality("Послушный, вежливый и тактичный")
        self.assertGreater(t["obedience"], 0.5)


class ReactionPolicyTest(unittest.TestCase):
    _NEUTRAL = {"obedience": 0.5, "persistence": 0.3, "touchiness": 0.3, "formality": 0.5}
    _STUBBORN = {"obedience": 0.2, "persistence": 0.9, "touchiness": 0.3, "formality": 0.2}
    _OBEDIENT = {"obedience": 0.9, "persistence": 0.1, "touchiness": 0.2, "formality": 0.8}
    _TOUCHY = {"obedience": 0.3, "persistence": 0.4, "touchiness": 0.9, "formality": 0.3}
    _INTERNAL = {"boredom": 0.1, "stress": 0.05}

    def test_return_welcome(self):
        d = ReactionPolicy.evaluate("return", self._INTERNAL, self._NEUTRAL)
        self.assertFalse(d["respect"])
        self.assertEqual(d["reaction"], "welcome")

    def test_obedient_respects_dnd(self):
        d = ReactionPolicy.evaluate("do_not_disturb", self._INTERNAL, self._OBEDIENT)
        self.assertTrue(d["respect"])
        self.assertEqual(d["reaction"], "respect_dnd")

    def test_stubborn_ignores_dnd(self):
        d = ReactionPolicy.evaluate("do_not_disturb", self._INTERNAL, self._STUBBORN)
        self.assertFalse(d["respect"])
        self.assertEqual(d["reaction"], "ignore_dnd")

    def test_persistent_insists_stay_on_goodbye(self):
        d = ReactionPolicy.evaluate("goodbye", self._INTERNAL, self._STUBBORN)
        self.assertFalse(d["respect"])
        self.assertEqual(d["reaction"], "insist_stay")

    def test_touchy_offended_on_goodbye(self):
        d = ReactionPolicy.evaluate("goodbye", self._INTERNAL, self._TOUCHY)
        self.assertFalse(d["respect"])
        self.assertEqual(d["reaction"], "offended")

    def test_sleep_respect_by_default(self):
        d = ReactionPolicy.evaluate("sleep", self._INTERNAL, self._NEUTRAL)
        self.assertTrue(d["respect"])

    def test_bored_stubborn_overrides_busy(self):
        internal = {"boredom": 0.9, "stress": 0.0}
        d = ReactionPolicy.evaluate("busy", internal, self._STUBBORN)
        self.assertFalse(d["respect"])


class GateTraitTest(unittest.TestCase):
    def test_dnd_blocked_for_obedient(self):
        user = {"signal": "do_not_disturb"}
        allowed, reason = InitiativeGate().allow(
            "initiate_dialogue",
            user,
            internal={"boredom": 0.1, "stress": 0.05},
            traits=TraitsProfile.from_personality("Послушный, тактичный"),
        )
        self.assertFalse(allowed)
        self.assertIn("respect_dnd", reason)

    def test_dnd_allowed_for_stubborn(self):
        user = {"signal": "do_not_disturb"}
        allowed, reason = InitiativeGate().allow(
            "initiate_dialogue",
            user,
            internal={"boredom": 0.8, "stress": 0.0},
            traits=TraitsProfile.from_personality("Упрямый, настойчивый"),
        )
        self.assertTrue(allowed)
        self.assertIn("override_", reason)

    def test_character_busy_always_denies(self):
        user = {"signal": "return"}
        allowed, reason = InitiativeGate().allow(
            "initiate_dialogue", user, busy=True
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "character_busy")


if __name__ == "__main__":
    unittest.main()
