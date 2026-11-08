"""Standalone-запуск пугалки fake_crash (зависание -> BSOD) без модели.

Запуск (из папки проекта):
    python scripts/debug_crash.py            # по умолчанию 5с freeze
    python scripts/debug_crash.py --sec 3   # 3с freeze

Показывает: зависание (скриншот, без курсора, звук уведомления — первые
0.3с в цикле) -> затем синий экран (BSOD). Это чистая имитация.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import mcp_system_interaction_server as server_module  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Run fake_crash prank standalone")
    ap.add_argument("--sec", type=float, default=5.0, help="длительность фазы зависания, сек")
    args = ap.parse_args()

    print(f"Запускаю fake_crash: freeze={args.sec}с -> BSOD")
    server_module._show_fake_crash(args.sec)
    print("Запущено. (Чтобы закрыть BSOD: Esc или через ~25с.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
