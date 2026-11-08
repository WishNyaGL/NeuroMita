"""Standalone-дебаг инструмента set_wallpaper_from_reactor.

Запуск (из папки проекта):
    python scripts/debug_reactor.py "MiSide Мита" --tags MiSide --tags Мита
    python scripts/debug_reactor.py "bleach" --tags Yoruichi --no-random-page

Скрипт показывает пошагово:
  - сформированный URL поиска;
  - сколько full-ссылок/миниатюр/страниц извлёк парсер (и сколько из них
    попало в аватарки — отфильтровано);
  - выбранную страницу (если random_page);
  - первые N кандидатов;
  - скачивание и проверку валидности;
  - НЕ устанавливает обои и НЕ пишет в Pictures.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Добавляем папку scripts в sys.path, чтобы импортировать сервер.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

# Импортируем сервер как модуль (он не запускается вне __main__).
import mcp_system_interaction_server as server_module  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Debug set_wallpaper_from_reactor")
    ap.add_argument("query", nargs="?", default="MiSide Мита", help="поисковый запрос")
    ap.add_argument("--tags", action="append", default=[], help="доп. тег (можно несколько)")
    ap.add_argument("--user", default="", help="автор (необязательно)")
    ap.add_argument("--no-random-page", action="store_true", help="не выбирать случайную страницу")
    ap.add_argument("--attempts", type=int, default=6, help="кол-во попыток скачивания")
    ap.add_argument("--limit", type=int, default=12, help="сколько кандидатов показать")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="не только найти, но и сохранить в Pictures и установить как обои",
    )
    args = ap.parse_args()

    print("=" * 70)
    print("Anime Reactor debug")
    print(f"  query={args.query!r}")
    print(f"  tags={args.tags!r}")
    print(f"  user={args.user!r}")
    print(f"  random_page={not args.no_random_page}")
    print("=" * 70)

    # 1. URL поиска (первый вариант)
    search_url = server_module._reactor_search_url(args.query, args.tags, args.user)
    print(f"\n[1] URL поиска (первый вариант):\n    {search_url}")

    # 2. Используем основной метод сервера (с ретраем по упрощённым вариантам)
    print("\n[2] Вызываю _reactor_find_full_url (с ретраем по вариантам)...")
    url, debug = server_module._reactor_find_full_url(
        args.query, args.tags, args.user,
        random_page=not args.no_random_page,
        attempts=args.attempts,
    )

    # Показываем диагностику вариантов.
    print("\n[3] Извлечённые варианты запроса:")
    for i, v in enumerate(debug.get("variants", []), 1):
        print(f"    {i}) query={v['query']!r} tags={v['tags']!r}")

    parsed = debug.get("parsed", {})
    for k, v in parsed.items():
        print(f"\n  [парсер] {k}: {v.get('summary', '')}")

    print(f"\n[4] target_page = {debug.get('target_page') or '(нет)'}")
    print(f"    attempts = {debug.get('attempts')}")
    print(f"    errors = {debug.get('errors')}")

    if not url:
        print("\n[ОШИБКА] не удалось найти полноразмерное изображение.")
        print(f"    детали: {debug}")
        return 1

    print(f"\n[5] УСПЕХ: {url}")
    # Дополнительно показываем, что это за изображение (по размеру).
    data, final_url = server_module._reactor_download(url)
    if data:
        print(f"    скачано {len(data)} байт")
        print(f"    итоговый URL: {final_url}")
        print(f"    валидное изображение: да")
    else:
        print("    [ПРЕДУПРЕЖДЕНИЕ] повторное скачивание не удалось (возможно временный сбой)")

    if args.apply:
        # Сохраняем в Pictures/NeuroMita/Wallpapers и устанавливаем обои.
        print("\n[6] --apply: сохраняю и устанавливаю обои...")
        library = server_module._wallpaper_library_dir()
        try:
            library.mkdir(parents=True, exist_ok=True)
            ext = ".jpg"
            low = url.lower()
            for e in server_module._IMAGE_EXTS:
                if low.endswith(e):
                    ext = e
                    break
            stem = (args.query or "anime")[:30].replace(" ", "_").replace("/", "_") or "anime"
            dest = library / f"reactor_{stem}{ext}"
            counter = 1
            while dest.exists():
                dest = library / f"reactor_{stem}_{counter}{ext}"
                counter += 1
            dest.write_bytes(data)
            print(f"    сохранено: {dest}")
        except Exception as exc:
            print(f"    [ОШИБКА] сохранить не удалось: {exc}")
            return 1

        if not server_module._set_wallpaper(dest):
            print("    [ОШИБКА] не удалось установить обои (SystemParametersInfo)")
            return 1
        print("    [УСПЕХ] обои установлены!")
        print("\n" + "=" * 70)
        print("Итог: обои установлены.")
        print(f"  файл: {dest}")
        print(f"  image_url = {url}")
        print("=" * 70)
        return 0

    print("\n" + "=" * 70)
    print("Результат (для установки можно вызвать инструмент):")
    print(f"  image_url = {url}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
