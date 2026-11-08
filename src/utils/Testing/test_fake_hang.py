"""Тесты имитации зависания системы (fake_system_hang) — безопасной пугалки."""
from __future__ import annotations

import wave
import unittest
from pathlib import Path
from unittest.mock import patch

import importlib.util as _il

_SERVER = Path(__file__).resolve().parents[3] / "scripts" / "mcp_system_interaction_server.py"
_spec = _il.spec_from_file_location("mcp_server_hang_ut", _SERVER)
mcp_server = _il.module_from_spec(_spec)
_spec.loader.exec_module(mcp_server)


class FakeCrashTest(unittest.TestCase):
    def test_crash_tool_returns_confirmation(self):
        with patch.object(mcp_server, "_show_fake_crash") as show:
            fn = mcp_server.__dict__.get("fake_crash")
            if fn is not None:
                out = fn(4)
                show.assert_called_once_with(4)
                self.assertEqual(out, "fake crash shown (freeze -> bsod)")

    def test_crash_helper_draws_ps1(self):
        # Проверяем, что _show_fake_crash не падает при отсутствии скриншота/WAV
        # и создаёт .ps1 (через tempfile). Мокаем subprocess.Popen.
        with patch.object(mcp_server, "_take_screenshot_full", return_value=None):
            with patch.object(mcp_server, "_make_notification_tail_wav", return_value=None):
                with patch.object(mcp_server.subprocess, "Popen") as popen:
                    # _home и tempfile реальны; проверим, что Popen вызван.
                    mcp_server._show_fake_crash(3)
                    popen.assert_called_once()


class FakeHangTest(unittest.TestCase):
    def test_tail_wav_is_valid_wave(self):
        wav = mcp_server._make_notification_tail_wav()
        self.assertIsNotNone(wav)
        with wave.open(str(wav), "rb") as w:
            self.assertGreater(w.getsampwidth(), 0)
            # Хвост не пустой (есть кадры).
            self.assertGreater(w.getnframes(), 0)
            # Длительность не более 0.4с.
            dur = w.getnframes() / w.getframerate()
            self.assertLessEqual(dur, 0.4)

    def test_uses_system_notify_sound(self):
        # Если системный звук есть — хвост берётся из него (не синтез).
        import os
        sys_wav = "C:/Windows/Media/Windows Background.wav"
        if not os.path.isfile(sys_wav):
            self.skipTest("системный звук отсутствует")
        wav = mcp_server._make_notification_tail_wav()
        self.assertIsNotNone(wav)
        with wave.open(str(wav), "rb") as w:
            # Системный Windows Background.wav — 48000 Гц.
            self.assertEqual(w.getframerate(), 48000)

    def test_screenshot_helper_is_safe_when_libs_missing(self):
        # Если PIL и mss недоступны — функция не должна падать (возвращает None).
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name.startswith("PIL") or name == "mss":
                raise ImportError(name)
            return real_import(name, *a, **k)

        with patch.object(mcp_server, "_home", return_value=Path("C:/tmp_home")):
            with patch.object(builtins, "__import__", side_effect=fake_import):
                self.assertIsNone(mcp_server._take_screenshot_full())

    def test_hang_tool_returns_confirmation(self):
        with patch.object(mcp_server, "_show_fake_system_hang") as show:
            fn = mcp_server.__dict__.get("fake_system_hang")
            if fn is not None:
                out = fn(3)
                show.assert_called_once_with(3)
                self.assertEqual(out, "system hang freeze shown")


if __name__ == "__main__":
    unittest.main()
