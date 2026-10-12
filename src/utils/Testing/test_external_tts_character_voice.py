from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_SRC = Path(__file__).resolve().parents[2]

if str(PROJECT_SRC) not in sys.path:
    sys.path.insert(0, str(PROJECT_SRC))

from services.external_tts_profiles import resolve_external_tts_voice_id


class ExternalTTSCharacterVoiceTests(unittest.TestCase):
    class Settings:
        def __init__(self, values):
            self.values = values

        def get(self, key, default=None):
            return self.values.get(key, default)

    def test_individual_voice_has_priority(self):
        settings = self.Settings({
            "EXTERNAL_TTS_CHARACTER_VOICES": {
                "Kind": "kind_voice",
            },
        })

        self.assertEqual(
            "kind_voice",
            resolve_external_tts_voice_id(
                settings,
                "Kind",
                {"external_voice_id": "legacy_voice"},
            ),
        )

    def test_legacy_character_voice_is_preserved(self):
        settings = self.Settings({
            "EXTERNAL_TTS_CHARACTER_VOICES": {},
        })

        self.assertEqual(
            "legacy_voice",
            resolve_external_tts_voice_id(
                settings,
                "Kind",
                {"external_voice_id": "legacy_voice"},
            ),
        )

    def test_global_voice_is_used_as_fallback(self):
        settings = self.Settings({})

        self.assertIsNone(
            resolve_external_tts_voice_id(
                settings,
                "Kind",
                {},
            )
        )

    def test_empty_individual_voice_falls_back_to_legacy(self):
        settings = self.Settings({
            "EXTERNAL_TTS_CHARACTER_VOICES": {
                "Kind": "",
            },
        })

        self.assertEqual(
            "legacy_voice",
            resolve_external_tts_voice_id(
                settings,
                "Kind",
                {"external_voice_id": "legacy_voice"},
            ),
        )

    def test_invalid_mapping_is_ignored(self):
        settings = self.Settings({
            "EXTERNAL_TTS_CHARACTER_VOICES": "invalid",
        })

        self.assertIsNone(
            resolve_external_tts_voice_id(
                settings,
                "Kind",
                {},
            )
        )


if __name__ == "__main__":
    unittest.main()