"""Тесты нормализации источника события (Изменение 1, Этап 1)."""
from __future__ import annotations

import unittest

from initiative_engine.observation.source import EventSource, normalize_source


class NormalizeSourceTest(unittest.TestCase):
    def test_player_sender(self):
        self.assertEqual(
            normalize_source("send_message", {"sender": "Player"}),
            EventSource.PLAYER,
        )

    def test_system_sender_is_not_initiative(self):
        # sender="System" НЕ должен считаться инициативой — это системная реплика.
        self.assertEqual(
            normalize_source("send_message", {"sender": "System"}),
            EventSource.SYSTEM,
        )

    def test_external_event_types(self):
        for ev_type in ("timer", "reminder", "idle_timeout", "camera", "periodic"):
            self.assertEqual(
                normalize_source("send_message", {"event_type": ev_type}),
                EventSource.EXTERNAL,
                ev_type,
            )

    def test_external_task_uid(self):
        self.assertEqual(
            normalize_source("send_message", {"task_uid": "task-1"}),
            EventSource.EXTERNAL,
        )

    def test_external_unity_retry(self):
        self.assertEqual(
            normalize_source("send_message", {"unity_retry_message_id": "m-1"}),
            EventSource.EXTERNAL,
        )

    def test_unknown_when_no_metadata(self):
        # Без sender/event_type/task_uid — unknown, а не player.
        self.assertEqual(
            normalize_source("send_message", {"user_input": "hello"}),
            EventSource.UNKNOWN,
        )

    def test_tool_source(self):
        self.assertEqual(
            normalize_source("tool.search", {"character_id": "Crazy"}),
            EventSource.TOOL,
        )

    def test_window_source(self):
        self.assertEqual(
            normalize_source("windows.active_window", {"summary": "..."}),
            EventSource.EXTERNAL,
        )

    def test_empty_payload_unknown(self):
        self.assertEqual(normalize_source("send_message", {}), EventSource.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
