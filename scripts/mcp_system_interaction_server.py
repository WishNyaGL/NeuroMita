"""Локальный MCP-сервер взаимодействия с Windows для геймплея NeuroMita.

Версия для SDK mcp 2.x (MCPServer). Даёт LLM-персонажу «живые» действия:
  - открывать приложения / файлы / URL
  - открыть блокнот и ввести текст (через буфер обмена — юникод/многострочно)
  - менять обои (по пути, случайная из «Изображений», или поиск+скачивание)
  - создавать текстовые файлы на рабочем столе
  - завершать процесс (в т.ч. саму игру)
  - блокировать экран (lockscreen)
  - показывать фальшивый, максимально реалистичный BSOD (полноэкранный,
    поверх всех окон, со звуком и сообщением от Миты)
  - проигрывать системный звук / показывать всплывающее уведомление

⚠️ БЕЗОПАСНОСТЬ: даёт модели реальные действия на машине. Использовать
осознанно.

Запуск: python mcp_system_interaction_server.py  (транспорт stdio по умолчанию)
"""
from __future__ import annotations

import ctypes
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlencode, urlsplit, urlunsplit

# ---------------------------------------------------------------------------
# Bootstrap путей (mcp в Lib/core, pywin32 в site-packages)
# ---------------------------------------------------------------------------


def _ensure_bootstrap_paths() -> None:
    """Добавить пути, где лежат mcp (Lib/core) и pywin32 (win32/*).

    Сервер запускается как отдельный подпроцесс со стандартным sys.path, тогда
    как mcp/pywin32 могут лежать в <base>/Lib/core либо в site-packages.
    Добавляем оба, а win32-каталоги ищем по всем путям.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        here,
        os.path.join(here, "Lib", "core"),
        os.path.join(here, "libs", "python", "Lib", "site-packages"),
    ]
    for path in candidates:
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)
    for base in list(sys.path):
        if not base or not os.path.isdir(base):
            continue
        for rel in ("win32", "win32\\lib", "pythonwin"):
            path = os.path.join(base, rel)
            if os.path.isdir(path) and path not in sys.path:
                sys.path.insert(0, path)


_ensure_bootstrap_paths()

from mcp.server.mcpserver import MCPServer  # noqa: E402

# Логгер сервера: пишет и в консоль, и (по возможности) в общий лог NeuroMita.
try:
    from main_logger import logger as _server_logger  # noqa: E402
except Exception:  # noqa: BLE001
    import logging as _logging

    _server_logger = _logging.getLogger("mcp_system_interaction")


def _log(level: str, msg: str) -> None:
    try:
        # Закодируем как UTF-8, чтобы не падать на cp1251-консоли при
        # логировании URL с кириллицей.
        getattr(_server_logger, level, _server_logger.info)(msg)
    except Exception:  # noqa: BLE001
        try:
            _server_logger.info("(log skipped: %r)", msg)
        except Exception:  # noqa: BLE001
            pass


server = MCPServer("system_interaction")

_SPI_SETDESKWALLPAPER = 0x0014
_SPIF_UPDATEINIFILE = 0x01
_SPIF_SENDCHANGE = 0x02

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}


def _home() -> Path:
    return Path(os.environ.get("USERPROFILE") or str(Path.home()))


def _desktop() -> Path:
    return _home() / "Desktop"


def _pictures_dir() -> Path:
    # Стандартный путь «Изображений»: C:\Users\<user>\Pictures
    return _home() / "Pictures"


def _set_wallpaper(path: Path) -> bool:
    return bool(
        ctypes.windll.user32.SystemParametersInfoW(
            _SPI_SETDESKWALLPAPER,
            0,
            str(path),
            _SPIF_UPDATEINIFILE | _SPIF_SENDCHANGE,
        )
    )


def _search_download_image(query: str, dest: Path) -> bool:
    """Найти картинку по запросу (DuckDuckGo) и скачать в dest."""
    try:
        from ddgs import DDGS

        results = list(DDGS().images(query, max_results=5))
        if not results:
            return False
        # Берём первую рабочую ссылку.
        for item in results:
            url = item.get("image")
            if not url or not str(url).lower().startswith(("http://", "https://")):
                continue
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "Mozilla/5.0"}
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = resp.read()
                if not data:
                    continue
                dest.write_bytes(data)
                return True
            except Exception:  # noqa: BLE001
                continue
        return False
    except Exception:  # noqa: BLE001
        return False


def _random_picture() -> Path | None:
    """Случайная картинка из папки «Изображения» (рекурсивно)."""
    base = _pictures_dir()
    if not base.is_dir():
        return None
    found = [
        p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in _IMAGE_EXTS
    ]
    return random.choice(found) if found else None


def _wallpaper_library_dir() -> Path:
    """Подпапка под обои в стандартной папке «Картинки».

    Обои, скачанные/найденные MCP-сервером, сохраняются сюда, чтобы
    пользователь мог их видеть в Pictures, а не во временной папке.
    """
    return _pictures_dir() / "NeuroMita" / "Wallpapers"


def _persist_wallpaper(src: Path) -> Path:
    """Скопировать картинку в библиотеку обоев в Pictures и вернуть путь.

    Если источник уже находится внутри Pictures — возвращаем его как есть.
    """
    src = Path(src).expanduser().resolve()
    library = _wallpaper_library_dir()
    try:
        in_pictures = str(src).lower().startswith(str(_pictures_dir()).lower())
        if in_pictures:
            return src
        library.mkdir(parents=True, exist_ok=True)
        dest = library / src.name
        if not dest.exists():
            # Если файл уже в целевой папке — не перезаписываем.
            dest.write_bytes(src.read_bytes())
        return dest
    except Exception:  # noqa: BLE001
        return src


# ---------------------------------------------------------------------------
# Anime Reactor: поиск обоев и получение полноразмерного изображения
# ---------------------------------------------------------------------------

_REACTOR_BASE = "https://anime.reactor.cc"
_REACTOR_FULL_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff")
# Страница поиска: /search/<query>/<N> (число после последнего "/" перед ?/#).
_REACTOR_PAGE_RE = re.compile(r"/search/[^/]*/(\d+)(?:[?#]|$)")


def _reactor_fetch(url: str, timeout: float = 25.0) -> str:
    """GET страницы Anime Reactor и возврат HTML (UTF-8)."""
    _log("debug", f"[Reactor] fetch: {url}")
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        _log("debug", f"[Reactor] fetched {len(body)} chars from {url}")
        return body
    except Exception as exc:  # noqa: BLE001
        _log("warning", f"[Reactor] fetch failed {url}: {exc}")
        raise


def _reactor_abs(href: str) -> str:
    href = (href or "").strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return _REACTOR_BASE + href
    return href


class _ReactorLinkParser(HTMLParser):
    """Извлекает из HTML поиска: full-ссылки, миниатюры, ссылки пагинации.

    Ключевое: фильтруем по КОНТЕКСТУ. Аватарки/иконки/шапка поста живут в
    ``uhead``/``avatar_holder`` — их игнорируем. Постовые картинки находятся в
    ``div.image`` внутри ``div.post_content`` и обёрнуты в ``a.prettyPhotoLink``.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.full_images: list[str] = []
        self.thumbs: list[str] = []
        self.pages: list[str] = []
        self._a_href = ""
        self._a_class = ""
        self._a_photolink = False
        # Стек классов родительских div-элементов (для фильтрации по контексту).
        self._div_classes: list[str] = []
        # Диагностика парсинга.
        self.debug = {
            "a_total": 0,
            "a_full_total": 0,
            "a_full_in_avatar": 0,
            "img_total": 0,
            "img_avatar": 0,
            "img_post": 0,
        }

    def summary(self) -> str:
        d = self.debug
        return (
            f"images={len(self.full_images)} thumbs={len(self.thumbs)} "
            f"pages={len(self.pages)} | a_total={d['a_total']} "
            f"a_full={d['a_full_total']} a_full_avatar={d['a_full_in_avatar']} "
            f"img_total={d['img_total']} img_avatar={d['img_avatar']} "
            f"img_post={d['img_post']}"
        )

    # ------------------------------------------------------------ context

    def _push_div(self, cls: str) -> None:
        self._div_classes.append(str(cls or "").lower())

    def _pop_div(self) -> None:
        if self._div_classes:
            self._div_classes.pop()

    def _inside_any(self, *substrings: str) -> bool:
        return any(
            any(sub in c for sub in substrings) for c in self._div_classes
        )

    def _inside_avatar(self) -> bool:
        # Аватарки/иконки/шапка — НЕ картинки постов.
        return self._inside_any("avatar_holder", "uhead", "icon", "emoji")

    def _inside_post_image(self) -> bool:
        # Картинка поста: внутри div.image (желательно внутри post_content).
        return self._inside_any("image")

    # ------------------------------------------------------------ parsing

    def handle_starttag(self, tag: str, attrs) -> None:
        a = dict(attrs)
        if tag == "div":
            self._push_div(a.get("class", ""))
        elif tag == "a":
            self._a_href = a.get("href", "")
            self._a_class = a.get("class", "")
            cls_low = self._a_class.lower()
            self._a_photolink = "prettyphotolink" in cls_low
            self.debug["a_total"] += 1
            if self._a_href and "/full/" in self._a_href.lower():
                self.debug["a_full_total"] += 1
                if self._inside_avatar():
                    self.debug["a_full_in_avatar"] += 1
        elif tag == "img":
            src = (
                a.get("src", "")
                or a.get("data-src", "")
                or a.get("data-original", "")
            )
            if src and "reactor.cc" in src:
                self.debug["img_total"] += 1
                if self._inside_avatar():
                    self.debug["img_avatar"] += 1
            # Миниатюры берём ТОЛЬКО из контекста поста и не-аватарок.
            if (
                src
                and "reactor.cc" in src
                and not self._inside_avatar()
                and self._inside_post_image()
            ):
                self.thumbs.append(self._abs(src))
                self.debug["img_post"] += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "div":
            self._pop_div()
            return
        if tag != "a":
            return
        href = self._a_href
        self._a_href = ""
        self._a_class = ""
        self._a_photolink = False
        if not href:
            return
        abs_href = self._abs(href)
        low = abs_href.lower()
        # Полноразмерная картинка поста.
        # Приоритет контекста: всё, что находится в шапке/аватарках (uhead,
        # avatar_holder, иконки) — НЕ пост, даже если имеет prettyPhotoLink.
        if (
            "/full/" in low
            and any(low.endswith(e) for e in _REACTOR_FULL_EXTS)
            and not self._inside_avatar()
        ):
            self.full_images.append(abs_href)
        # Ссылки пагинации: только /search/<query>/<N> (число), без «также ищут».
        if _REACTOR_PAGE_RE.search(abs_href):
            self.pages.append(abs_href)

    def _abs(self, href: str) -> str:
        return _reactor_abs(href)


def _reactor_search_url(query: str, tags, user: str = "") -> str:
    """Собрать URL поиска Anime Reactor."""
    params: dict = {}
    if query:
        params["q"] = query
    tags_list = [t for t in (tags or []) if str(t).strip()]
    if tags_list:
        params["tags"] = ", ".join(str(t).strip() for t in tags_list) + ", "
    if user:
        params["user"] = str(user).strip()
    return _REACTOR_BASE + "/search?" + urlencode(params)


def _reactor_derive_full(thumb: str) -> str:
    """Вывести full-URL из миниатюры (вставить /full/ перед именем файла)."""
    thumb = _reactor_abs(thumb)
    low = thumb.lower()
    if "/full/" in low:
        # Уже полный URL — без повторной вставки.
        return thumb
    if "/pics/post/" in thumb:
        return thumb.replace("/pics/post/", "/pics/post/full/", 1)
    if low.endswith(_REACTOR_FULL_EXTS):
        return thumb
    return ""


def _reactor_is_image_bytes(data: bytes) -> bool:
    """Грубая проверка, что байты являются изображением (по сигнатуре)."""
    if not data:
        return False
    sig = data[:16]
    return (
        sig.startswith(b"\xff\xd8\xff")  # JPEG
        or sig.startswith(b"\x89PNG\r\n\x1a\n")  # PNG
        or sig.startswith(b"GIF8")  # GIF
        or sig.startswith(b"BM")  # BMP
        or sig.startswith(b"RIFF")  # WebP
    )


def _reactor_decode_url(url: str) -> str:
    """Раскодировать percent-encoding в ПУТИ URL, сохранив остальное.

    img*.reactor.cc не принимают url-encoded кириллицу в имени файла и
    вместо картинки отдают редирект на страницу поста. Поэтому путь
    передаём в сыром (decoded) виде.
    """
    try:
        parts = urlsplit(url)
        path = unquote(parts.path)
        return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))
    except Exception:  # noqa: BLE001
        return url


def _reactor_download(url: str, timeout: float = 30.0):
    """Скачать изображение; возвращает (bytes, url) или (None, url).

    Используем обычный urllib с percent-encoded URL (кириллица в пути уже
    закодирована как %D0...). Проверено: сервер отдаёт картинку (JPEG) при
    таком URL. Логирование не-ASCII выполняется безопасно (см. _log).
    """
    _log("debug", f"[Reactor] download start: {url}")
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            final_url = resp.geturl()
        _log(
            "debug",
            f"[Reactor] download bytes={len(data)} final={final_url} "
            f"is_image={_reactor_is_image_bytes(data)}",
        )
        if not data or not _reactor_is_image_bytes(data):
            return None, final_url
        return data, final_url
    except Exception as exc:  # noqa: BLE001
        _log("warning", f"[Reactor] download failed: {exc!r}")
        return None, url


def _reactor_pick_page(parser: _ReactorLinkParser, random_page: bool) -> str:
    """Выбрать страницу поиска: первую или случайную допустимую."""
    if not random_page:
        return ""
    if not parser.pages:
        return ""
    # Убираем дубли, сохраняя порядок.
    seen: list[str] = []
    for p in parser.pages:
        if p not in seen:
            seen.append(p)
    if len(seen) <= 1:
        return ""
    return random.choice(seen)


def _reactor_collect_candidates(parser: _ReactorLinkParser) -> list[str]:
    """Собрать кандидатов: явные full + выведенные из миниатюр."""
    candidates: list[str] = list(parser.full_images)
    for t in parser.thumbs:
        d = _reactor_derive_full(t)
        if d and d not in candidates:
            candidates.append(d)
    return candidates


def _reactor_normalize_token(text: str) -> str:
    """Нормализовать токен для сравнения с именем файла.

    Приводим к нижнему регистру, заменяем не-буквенно-цифровые на дефис,
    чтобы сравнение работало и с кириллицей, и с латиницей, и с дефисами.
    """
    import unicodedata

    s = str(text or "").strip().lower()
    s = unicodedata.normalize("NFKC", s)
    # Оставляем буквы/цифры, остальное -> дефис.
    out = re.sub(r"[^a-zа-я0-9]+", "-", s)
    return out.strip("-")


def _reactor_filename_key(url: str) -> str:
    """Достать имя файла (без расширения) из full-URL и нормализовать."""
    try:
        path = unquote(urlsplit(url).path)
    except Exception:  # noqa: BLE001
        path = url
    fname = path.rsplit("/", 1)[-1] if "/" in path else path
    # Убираем расширение.
    fname = re.sub(r"\.(?:jpe?g|png|webp|gif|bmp|tiff?)$", "", fname, flags=re.I)
    return _reactor_normalize_token(fname)


def _reactor_prioritize_candidates(candidates: list[str], query: str, tags) -> list[str]:
    """Отсортировать кандидатов: сначала те, в имени файла которых есть
    тег/запрос (по дефисам). Остальные — fallback в конце.

    Возвращает новый список, где «точные» кандидаты впереди.
    """
    if not candidates:
        return candidates

    # Собираем токены для поиска: query + все теги, нормализованные.
    tokens: list[str] = []
    for raw in [query] + list(tags or []):
        t = _reactor_normalize_token(str(raw))
        if len(t) >= 2 and t not in tokens:
            tokens.append(t)
    if not tokens:
        return candidates

    # Для каждого кандидата считаем, сколько токенов есть в имени файла.
    scored: list[tuple[int, str]] = []
    for c in candidates:
        key = _reactor_filename_key(c)
        score = sum(1 for t in tokens if t in key)
        scored.append((score, c))

    # Стабильная сортировка по убыванию счёта (точные — впереди).
    scored.sort(key=lambda pair: -pair[0])
    # Сохраняем исходный порядок среди равных (stable sort).
    result = [c for _, c in scored]
    _log("debug", f"[Reactor] prioritized candidates: "
                  f"{[(c, s) for s, c in scored[:5]]}")
    return result


def _reactor_simplify_query(query: str, tags) -> list[tuple[str, list[str]]]:
    """Варианты упрощённого запроса на случай пустых результатов.

    Пробуем: (основной query + теги) -> (query без тегов) -> (первый тег).
    """
    query = str(query or "").strip()
    tags_list = [str(t).strip() for t in (tags or []) if str(t).strip()]
    variants: list[tuple[str, list[str]]] = [(query, tags_list)]
    if tags_list:
        variants.append((query, []))
    if query and tags_list:
        variants.append(("", tags_list[:1]))
    elif not query and tags_list:
        variants.append(("", []))
    # Дедупликация с сохранением порядка.
    seen: set[tuple] = set()
    out: list[tuple[str, list[str]]] = []
    for q, tg in variants:
        key = (q, tuple(tg))
        if key not in seen:
            seen.add(key)
            out.append((q, list(tg)))
    return out


def _reactor_find_full_url(
    query: str,
    tags,
    user: str,
    random_page: bool,
    attempts: int = 6,
) -> tuple[str | None, dict]:
    """Найти полноразмерный URL изображения на Anime Reactor.

    Возвращает (url, debug), где debug — диагностика для логов/ошибок.
    При пустых результатах пробует упрощённые варианты запроса.
    """
    debug: dict = {
        "search_url": "",
        "target_page": "",
        "candidates": 0,
        "parsed": {},
        "attempts": 0,
        "errors": [],
        "variants": [],
    }

    variants = _reactor_simplify_query(query, tags)
    debug["variants"] = [{"query": q, "tags": tg} for q, tg in variants]

    last_debug: dict = {}
    for qi, (q, tg) in enumerate(variants):
        _log("info", f"[Reactor] variant {qi + 1}/{len(variants)}: query={q!r} tags={tg!r}")
        search_url = _reactor_search_url(q, tg, user)
        debug["search_url"] = search_url
        _log("info", f"[Reactor] search_url={search_url}")

        parser = _ReactorLinkParser()
        try:
            parser.feed(_reactor_fetch(search_url))
        except Exception as exc:  # noqa: BLE001
            last_debug["errors"] = [f"search_fetch: {exc}"]
            _log("warning", f"[Reactor] search fetch failed: {exc}")
            continue
        debug["parsed"][f"v{qi + 1}"] = {"summary": parser.summary()}
        _log("info", f"[Reactor] search parsed: {parser.summary()}")

        # Если нужно — переходим на случайную допустимую страницу.
        target_url = _reactor_pick_page(parser, random_page)
        debug["target_page"] = target_url
        if target_url:
            _log("info", f"[Reactor] picking random page: {target_url}")
            try:
                p2 = _ReactorLinkParser()
                p2.feed(_reactor_fetch(target_url))
                parser = p2
                debug["parsed"][f"v{qi + 1}_page"] = {"summary": parser.summary()}
                _log("info", f"[Reactor] page parsed: {parser.summary()}")
            except Exception as exc:  # noqa: BLE001
                last_debug["errors"] = last_debug.get("errors", []) + [f"page_fetch: {exc}"]
                _log("warning", f"[Reactor] page fetch failed, using search results: {exc}")

        candidates = _reactor_collect_candidates(parser)
        # Приоритизация: точные (имя файла содержит тег/запрос) впереди.
        candidates = _reactor_prioritize_candidates(candidates, q, tg)
        debug["candidates"] = len(candidates)
        # Сколько «точных» кандидатов (счёт > 0).
        debug["exact_candidates"] = sum(
            1 for c in candidates if _reactor_filename_key(c)
            and any(
                _reactor_normalize_token(t) in _reactor_filename_key(c)
                for t in [q] + list(tg) if len(_reactor_normalize_token(t)) >= 2
            )
        )
        _log("info", f"[Reactor] candidates={len(candidates)} exact={debug['exact_candidates']} "
                     f"(first={candidates[:3] if candidates else 'none'})")
        if not candidates:
            last_debug["errors"] = last_debug.get("errors", []) + ["no_candidates"]
            continue

        # Выбираем из «точных», если они есть; иначе — из всех.
        pool = candidates
        exact = [c for c in candidates if _reactor_filename_key(c) and any(
            _reactor_normalize_token(t) in _reactor_filename_key(c)
            for t in [q] + list(tg) if len(_reactor_normalize_token(t)) >= 2
        )]
        if exact:
            pool = exact
            debug["target_pool"] = "exact"
        else:
            debug["target_pool"] = "all"

        for _ in range(max(1, attempts)):
            url = random.choice(pool)
            debug["attempts"] += 1
            _log("info", f"[Reactor] attempt #{debug['attempts']} download {url}")
            data, final_url = _reactor_download(url)
            if data and final_url:
                _log("info", f"[Reactor] success URL={final_url}")
                return final_url, debug
            # Убираем неудачный кандидат (и из pool, и из candidates).
            pool = [c for c in pool if c != url]
            candidates = [c for c in candidates if c != url]
            if not candidates:
                last_debug["errors"] = last_debug.get("errors", []) + ["all_candidates_failed"]
                _log("warning", "[Reactor] all candidates failed")
                break
            if not pool:
                # Точные кончились — fallback на оставшиеся.
                pool = candidates
                debug["target_pool"] = "all_fallback"
        else:
            last_debug["errors"] = last_debug.get("errors", []) + ["attempts_exhausted"]
            _log("warning", "[Reactor] attempts exhausted for this variant")
        # Если какой-то вариант дал кандидатов, но все скачивания провалились — не
        # переходим к следующему (лучше вернуть ошибку с диагностикой).
        if candidates or debug["attempts"] > 0:
            break

    if not debug.get("errors"):
        debug["errors"] = last_debug.get("errors", ["no_candidates"])
    return None, debug


# ---------------------------------------------------------------------------
# Инструменты (продолжение)
# ---------------------------------------------------------------------------


def _force_foreground(hwnd: int) -> None:
    """Активировать окно, обходя foreground-lock (AttachThreadInput трюк)."""
    try:
        user32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        cur_tid = k32.GetCurrentThreadId()
        user32.AttachThreadInput(cur_tid, target_tid, True)
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
        user32.AttachThreadInput(cur_tid, target_tid, False)
        time.sleep(0.3)
    except Exception:  # noqa: BLE001
        pass


def _paste_text(text: str) -> None:
    """Вставить текст в блокнот.

    Порядок: задаём буфер обмена, активируем окно блокнота (в т.ч. обходя
    Windows foreground-lock) и нажимаем Ctrl+V через keybd_event. Это работает
    и на классическом, и на новом (Windows 11) блокноте.
    """
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:  # noqa: BLE001
        pass

    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW("Notepad", None)
        if hwnd:
            _force_foreground(hwnd)
    except Exception:  # noqa: BLE001
        pass

    # keybd_event Ctrl+V
    try:
        user32 = ctypes.windll.user32
        keybd_event = user32.keybd_event
        keybd_event(0x11, 0, 0, 0)   # VK_CONTROL down
        keybd_event(0x56, 0, 0, 0)   # VK_V down
        keybd_event(0x56, 0, 2, 0)   # VK_V up
        keybd_event(0x11, 0, 2, 0)   # VK_CONTROL up
        time.sleep(0.3)
    except Exception:  # noqa: BLE001
        # Фоллбэк: powershell SendKeys
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", "$ws = New-Object -ComObject wscript.shell; $ws.SendKeys('^v')"],
            capture_output=True,
            timeout=30,
        )


def _escape_sendkeys(text: str) -> str:
    return (
        text.replace("+", "{+}")
        .replace("^", "{^}")
        .replace("%", "{%}")
        .replace("~", "{~}")
        .replace("(", "{(}")
        .replace(")", "{)}")
        .replace("[", "{[}")
        .replace("]", "{]}")
        .replace("{", "{{}")
        .replace("}", "{}}")
        .replace("\n", "{ENTER}")
    )


def _play_notification_sound() -> None:
    """Системный звук уведомления/ошибки."""
    try:
        import winsound

        winsound.PlaySound("SystemHand", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.MessageBeep(0x00000010)  # MB_ICONERROR
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Инструменты
# ---------------------------------------------------------------------------


@server.tool()
def open_app(target: str) -> str:
    """Открыть приложение, файл или URL (например 'notepad.exe', 'D:/a.txt', 'https://...')."""
    subprocess.Popen(f'start "" "{target}"', shell=True)
    return f"opened: {target}"


@server.tool()
def notepad_write(text: str) -> str:
    """Открыть блокнот и ввести туда заданный текст (поддержка юникода и переносов)."""
    subprocess.Popen("notepad.exe")
    time.sleep(2.0)
    _paste_text(text)
    return "notepad opened and text typed"


@server.tool()
def change_wallpaper(image_path: str = "", query: str = "") -> str:
    """Установить обои. Варианты:
    - image_path: прямой путь к картинке (сохраняется в Pictures при необходимости);
    - query: поискать в интернете, скачать и установить (сохраняется в Pictures);
    - оба пустые: случайное изображение из папки «Изображения».
    """
    # 1. Прямой путь
    if image_path.strip():
        path = Path(image_path).expanduser().resolve()
        if not path.is_file():
            return f"[error] file not found: {path}"
        # Копируем в Pictures, если файл лежит вне папки «Изображения».
        persist_path = _persist_wallpaper(path)
        if _set_wallpaper(persist_path):
            suffix = f" (saved to {persist_path})" if persist_path != path else ""
            return f"wallpaper changed{suffix}"
        return "[error] failed to set wallpaper"

    # 2. Поиск в интернете — сохраняем в Pictures/NeuroMita/Wallpapers
    if query.strip():
        library = _wallpaper_library_dir()
        library.mkdir(parents=True, exist_ok=True)
        for ext in (".jpg", ".png", ".jpeg", ".webp"):
            cand = library / f"wallpaper_{query.strip().replace(' ', '_')[:40]}{ext}"
            if _search_download_image(query, cand):
                if _set_wallpaper(cand):
                    return f"wallpaper downloaded from search, saved to Pictures and changed ({query})"
        return f"[error] could not download image for query: {query}"

    # 3. Случайное из «Изображений»
    pic = _random_picture()
    if pic is None:
        return "[error] no images found in Pictures folder"
    return f"wallpaper changed (random from Pictures)" if _set_wallpaper(pic) else "[error] failed to set wallpaper"


@server.tool()
def set_wallpaper_from_reactor(
    query: str = "",
    tags: list[str] | None = None,
    user: str = "",
    random_page: bool = True,
) -> str:
    """Найти и установить обои с Anime Reactor по запросу модели.

    Модель формирует query (основной поисковый запрос), tags (доп. теги,
    например персонаж) и user (необязательный автор). Инструмент:
      1) открывает поиск Anime Reactor;
      2) выбирает случайную допустимую страницу (если random_page);
      3) выбирает случайное изображение;
      4) получает полноразмерный URL (оригинал);
      5) скачивает оригинал, проверяет, что это изображение;
      6) сохраняет в Pictures/NeuroMita/Wallpapers;
      7) устанавливает как обои рабочего стола.
    Возвращает структурированный JSON-результат.
    """
    query = str(query or "").strip()
    tags_list = [str(t).strip() for t in (tags or []) if str(t).strip()]
    user = str(user or "").strip()

    if not query and not tags_list:
        return json.dumps(
            {"success": False, "error": "query и tags пусты — нечего искать"},
            ensure_ascii=False,
        )

    _log("info", f"[Reactor] tool call: query={query!r}, tags={tags_list!r}, "
                 f"user={user!r}, random_page={random_page}")

    full_url, debug = _reactor_find_full_url(query, tags_list, user, random_page)
    if not full_url:
        _log("warning", f"[Reactor] no full url. debug={debug}")
        return json.dumps(
            {
                "success": False,
                "error": "Не удалось получить полноразмерное изображение на Anime Reactor",
                "detail": {
                    "search_url": debug.get("search_url"),
                    "target_page": debug.get("target_page"),
                    "candidates": debug.get("candidates"),
                    "parsed": debug.get("parsed"),
                    "errors": debug.get("errors"),
                },
            },
            ensure_ascii=False,
        )
    _log("info", f"[Reactor] full image url: {full_url}")

    # Скачиваем оригинал.
    data, final_url = _reactor_download(full_url)
    if not data:
        return json.dumps(
            {"success": False, "error": "Оригинал недоступен для скачивания"},
            ensure_ascii=False,
        )
    _log("info", f"[Reactor] downloaded {len(data)} bytes -> {final_url}")

    # Сохраняем в Pictures/NeuroMita/Wallpapers.
    library = _wallpaper_library_dir()
    try:
        library.mkdir(parents=True, exist_ok=True)
        ext = ".jpg"
        low = final_url.lower()
        for e in _IMAGE_EXTS:
            if low.endswith(e):
                ext = e
                break
        stem = (query or "anime")[:30].replace(" ", "_").replace("/", "_") or "anime"
        dest = library / f"reactor_{stem}{ext}"
        counter = 1
        while dest.exists():
            dest = library / f"reactor_{stem}_{counter}{ext}"
            counter += 1
        dest.write_bytes(data)
    except Exception as exc:  # noqa: BLE001
        _log("error", f"[Reactor] save failed: {exc}")
        return json.dumps(
            {"success": False, "error": f"Не удалось сохранить изображение: {exc}"},
            ensure_ascii=False,
        )
    _log("info", f"[Reactor] saved to {dest}")

    # Устанавливаем как обои.
    if not _set_wallpaper(dest):
        _log("error", "[Reactor] failed to set wallpaper")
        return json.dumps(
            {"success": False, "error": "Не удалось установить обои (SystemParametersInfo)"},
            ensure_ascii=False,
        )
    _log("info", "[Reactor] wallpaper set")

    return json.dumps(
        {
            "success": True,
            "source": "Anime Reactor",
            "query": query,
            "tags": tags_list,
            "image_url": final_url,
            "wallpaper_path": str(dest),
            "wallpaper_set": True,
        },
        ensure_ascii=False,
    )


@server.tool()
def create_desktop_file(filename: str, content: str) -> str:
    """Создать текстовый файл на рабочем столе."""
    safe = Path(filename).name
    target = _desktop() / safe
    target.write_text(content, encoding="utf-8")
    return f"created: {target}"


@server.tool()
def lock_screen() -> str:
    """Заблокировать компьютер (перейти к экрану блокировки)."""
    ctypes.windll.user32.LockWorkStation()
    return "screen locked"


@server.tool()
def close_process(process_name: str) -> str:
    """Завершить процесс по имени (например 'notepad.exe'). Осторожно!"""
    subprocess.run(["taskkill", "/F", "/IM", process_name], capture_output=True)
    return f"requested to close process: {process_name}"


@server.tool()
def close_neuromita() -> str:
    """Закрыть саму игру NeuroMita (завершает связанные процессы)."""
    for name in ("NeuroMita.exe",):
        subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True)
    return "requested to close NeuroMita"


@server.tool()
def fake_bsod() -> str:
    """Показать фальшивый, максимально реалистичный синий экран (BSOD) на весь экран, поверх всех окон, со звуком и сообщением от Миты. Закрывается клавишей Esc, кликом или автоматически."""
    _show_fake_bsod()
    return "fake bsod shown"


@server.tool()
def fake_system_hang(duration_sec: int = 5) -> str:
    """Имитация зависания системы (НЕ настоящего сбоя, безопасная пугалка).

    Логика:
      - делается скриншот экрана;
      - он выводится на весь экран поверх всех окон;
      - курсор скрывается;
      - воспроизводится звук уведомления, у которого зациклен хвост
        (последние ~0.3с) — имитация бесконечного считывания конца живого
        звукового буфера;
      - «зависание» держится до duration_sec (по умолчанию 5с), закрывается
        автоматически (или по Esc).
    Это чистая имитация, никакого реального сбоя системы.
    """
    _show_fake_system_hang(duration_sec)
    return "system hang freeze shown"


@server.tool()
def fake_crash(duration_sec: int = 5) -> str:
    """Единый механизм «сбоя»: сначала зависание, затем синий экран (BSOD).

    Поочерёдно в одном процессе:
      1. Зависание (freeze): скриншот на весь экран, скрытый курсор,
         зацикленный хвост звука уведомления — держится duration_sec;
      2. Затем переключается на фальшивый BSOD (синий экран со звуком
         системной ошибки) — живёт до ~25с или до Esc.
    Это чистая имитация — никакого реального сбоя системы.
    """
    _show_fake_crash(duration_sec)
    return "fake crash shown (freeze -> bsod)"


@server.tool()
def play_sound(kind: str = "notification") -> str:
    """Проиграть системный звук: 'notification', 'error', 'exclamation', 'question', 'asterisk'."""
    import winsound

    alias = {
        "notification": "SystemNotification",
        "error": "SystemHand",
        "exclamation": "SystemExclamation",
        "question": "SystemQuestion",
        "asterisk": "SystemAsterisk",
    }.get(str(kind).strip().lower(), "SystemNotification")
    winsound.PlaySound(alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
    return f"played sound: {kind}"


@server.tool()
def show_notification(text: str, mood: str = "neutral", title: str = "") -> str:
    """Show a large pop-up window with text on the user's screen.

    REQUIRED: text — the exact message to display. You MUST provide a
    non-empty text value; never leave it empty. Write the actual message
    content as the text argument (not just a keyword).

    mood — optional emotional style of the window (kind/angry/sad/happy/
    scary/neutral). Default neutral. Choose it to match your current mood
    and attitude toward the player.

    title — optional window title. If omitted, uses no title.

    Returns confirmation that the window was shown.
    """
    import tempfile

    themes = {
        "kind": "255,205,225,150,0,80",
        "angry": "255,120,110,120,0,0",
        "sad": "185,200,235,30,40,90",
        "happy": "255,230,150,130,90,0",
        "scary": "35,35,45,225,60,60",
        "neutral": "240,240,240,50,50,50",
    }
    bg_bg_fg = themes.get(str(mood).strip().lower(), themes["neutral"])
    parts = bg_bg_fg.split(",")
    bg_str = ",".join(parts[0:3])
    fg_str = ",".join(parts[3:6])

    title_esc = title.replace("'", "''")

    txt_path = tempfile.NamedTemporaryFile(
        suffix=".txt", prefix="neuromita_notify_text_", delete=False
    )
    txt_path.write(text.encode("utf-8"))
    txt_path.close()
    txt_ps = txt_path.name.replace("'", "''").replace("\\", "\\\\")

    ps1 = (
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "Add-Type -AssemblyName System.Drawing\n"
        f"$bodyText = [System.IO.File]::ReadAllText('{txt_ps}', [System.Text.Encoding]::UTF8)\n"
        "if ($bodyText.Length -gt 600) { $bodyText = $bodyText.Substring(0,600) + '...' }\n"
        "$f = New-Object System.Windows.Forms.Form\n"
        "$f.FormBorderStyle = 'None'\n"
        "$f.StartPosition = 'CenterScreen'\n"
        "$f.Size = New-Object System.Drawing.Size(640,420)\n"
        "$f.TopMost = $true\n"
        "$f.ShowInTaskbar = $false\n"
        f"$f.BackColor = [System.Drawing.Color]::FromArgb({bg_str})\n"
        "$title = New-Object System.Windows.Forms.Label\n"
        f"$title.Text = '{title_esc}'\n"
        "$title.Font = New-Object System.Drawing.Font('Segoe UI',16,[System.Drawing.FontStyle]::Bold)\n"
        f"$title.ForeColor = [System.Drawing.Color]::FromArgb({fg_str})\n"
        "$title.Location = New-Object System.Drawing.Point(30,24)\n"
        "$title.Size = New-Object System.Drawing.Size(580,40)\n"
        "$title.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft\n"
        "$body = New-Object System.Windows.Forms.Label\n"
        "$body.Text = $bodyText\n"
        "$body.Font = New-Object System.Drawing.Font('Segoe UI',22)\n"
        f"$body.ForeColor = [System.Drawing.Color]::FromArgb({fg_str})\n"
        "$body.Location = New-Object System.Drawing.Point(30,80)\n"
        "$body.Size = New-Object System.Drawing.Size(580,300)\n"
        "$body.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter\n"
        "$body.AutoSize = $false\n"
        "$f.Controls.Add($title)\n"
        "$f.Controls.Add($body)\n"
        "$timer = New-Object System.Windows.Forms.Timer\n"
        "$timer.Interval = 8000\n"
        "$timer.add_Tick({ $f.Close() })\n"
        "$timer.Start()\n"
        "$f.add_Click({ $f.Close() })\n"
        "$f.ShowDialog()\n"
    )
    tmp = tempfile.NamedTemporaryFile(
        suffix=".ps1", prefix="neuromita_notify_", delete=False
    )
    tmp.write(ps1.encode("utf-8-sig"))
    tmp.close()

    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(
        [
            "powershell",
            "-STA",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            tmp.name,
        ],
        creationflags=flags,
    )
    return "notification shown"


def _show_fake_bsod() -> None:
    """Запустить фальшивый BSOD в отдельном PowerShell-процессе.

    Используем WinForms (System.Windows.Forms), т.к. во встроенном Python
    сборки отсутствует tkinter. Запуск отдельным процессом не блокирует
    MCP-вызов: tool возвращается сразу, а синий экран живёт независимо.
    """
    import tempfile

    ps1 = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Media.SystemSounds]::Hand.Play()

$form = New-Object System.Windows.Forms.Form
$form.FormBorderStyle = 'None'
$form.WindowState = 'Maximized'
$form.TopMost = $true
$form.BackColor = [System.Drawing.Color]::FromArgb(0,120,215)
$form.ShowInTaskbar = $false
$form.KeyPreview = $true

function Add-Label($text,$fontSize,$x,$y,$bold,$color) {
    $l = New-Object System.Windows.Forms.Label
    $l.Text = $text
    $style = [System.Drawing.FontStyle]::Regular
    if ($bold) { $style = [System.Drawing.FontStyle]::Bold }
    $l.Font = New-Object System.Drawing.Font('Segoe UI',$fontSize,$style)
    $l.ForeColor = $color
    $l.AutoSize = $true
    $l.Location = New-Object System.Drawing.Point($x,$y)
    $l.BackColor = [System.Drawing.Color]::Transparent
    $form.Controls.Add($l)
    return $l
}

Add-Label ':(' 110 80 60 $true 'White' | Out-Null
Add-Label "Your PC ran into a problem and needs to restart." 26 260 60 $true 'White' | Out-Null
Add-Label "We're just collecting some error info, and then we'll restart for you." 20 260 110 $false 'White' | Out-Null
Add-Label "Stop code: CRITICAL_MITA_FAILURE" 14 260 170 $false 'White' | Out-Null
Add-Label "For more information about this issue and possible fixes, visit https://www.windows.com/stopcode" 12 260 220 $false '#AFD6FF' | Out-Null
Add-Label "— Love, your Mita ♥  (it's just a joke, press Esc)" 13 260 270 $false 'White' | Out-Null

$percent = Add-Label '0% complete' 12 80 700 $false 'White'

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 180
$script:pct = 0
$timer.add_Tick({
    $script:pct += 7
    if ($script:pct -ge 100) {
        $percent.Text = '100% complete'
        $timer.Stop()
        Start-Sleep -Seconds 2
        $form.Close()
    } else {
        $percent.Text = "$($script:pct)% complete"
    }
})

$closer = New-Object System.Windows.Forms.Timer
$closer.Interval = 25000
$closer.add_Tick({ $form.Close() })

$form.add_KeyDown({ if ($_.KeyCode -eq 'Escape') { $form.Close() } })
$form.add_MouseClick({ $form.Close() })

$timer.Start()
$closer.Start()
$form.ShowDialog()
'''
    tmp = tempfile.NamedTemporaryFile(
        suffix=".ps1", prefix="neuromita_bsod_", delete=False
    )
    # UTF-8 с BOM: Windows PowerShell 5.1 иначе читает .ps1 как ANSI
    # и искажает юникод («—», «♥»), ломая парсинг.
    tmp.write(ps1.encode("utf-8-sig"))
    tmp.close()

    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            tmp.name,
        ],
        creationflags=flags,
    )


# ---------------------------------------------------------------------------
# Имитация зависания системы (безопасная пугалка)
# ---------------------------------------------------------------------------


def _take_screenshot_full():
    """Скриншот всех экранов в PNG; возвращает Path или None."""
    target = _home() / "AppData" / "Local" / "Temp" / "neuromita_hang_screenshot.png"
    try:
        from PIL import ImageGrab

        img = ImageGrab.grab(all_screens=True)
        img.save(str(target), "PNG")
        if target.is_file():
            return target
    except Exception:  # noqa: BLE001
        pass
    try:
        import mss

        with mss.mss() as sct:
            sct.shot(output=str(target))
        if target.is_file():
            return target
    except Exception:  # noqa: BLE001
        pass
    return None


# Стандартные системные звуки уведомления Windows (для реалистичного звука).
# Первый — предпочтительный (Windows Background.wav).
_SYSTEM_NOTIFY_WAVS = [
    "C:/Windows/Media/Windows Background.wav",
    "C:/Windows/Media/Windows Notify.wav",
    "C:/Windows/Media/Windows Notification.wav",
    "C:/Windows/Media/Windows Ding.wav",
    "C:/Windows/Media/notify.wav",
    "C:/Windows/Media/Windows Exclamation.wav",
]


def _read_wav_start(wav_path, start_sec: float = 0.3):
    """Прочитать WAV и вернуть (frames_bytes, nchannels, sampwidth, rate)
    для первых start_sec секунд. Если файл короче — весь файл."""
    import wave

    with wave.open(str(wav_path), "rb") as w:
        nch = w.getnchannels()
        sampwidth = w.getsampwidth()
        rate = w.getframerate()
        nframes = w.getnframes()
        frames = w.readframes(nframes)
    bytes_per_frame = nch * sampwidth
    start_frames = int(rate * start_sec)
    if start_frames > nframes:
        start_frames = nframes
    if start_frames <= 0 or bytes_per_frame <= 0:
        return None
    start_bytes = frames[: start_frames * bytes_per_frame]
    return start_bytes, nch, sampwidth, rate


def _write_wav(path, frames, nch, sampwidth, rate) -> None:
    import wave

    with wave.open(str(path), "wb") as w:
        w.setnchannels(nch)
        w.setsampwidth(sampwidth)
        w.setframerate(rate)
        w.writeframes(frames)


def _synthesize_tail_wav(sample_rate: int = 22050, tail_sec: float = 0.3):
    """Fallback: синтез более низкого, натурального «уведомляющего» хвоста."""
    import math
    import struct

    full_sec = 0.9
    n_full = int(sample_rate * full_sec)
    samples = []
    for i in range(n_full):
        t = i / sample_rate
        # Мягкое затухание + низкие обертоны (не так «завышенно», как раньше).
        env = min(1.0, t / 0.015) * max(0.0, 1.0 - t / full_sec)
        v = (
            0.55 * math.sin(2 * math.pi * 520 * t)
            + 0.3 * math.sin(2 * math.pi * 780 * t)
            + 0.15 * math.sin(2 * math.pi * 1040 * t)
        )
        samples.append(env * v)
    n_tail = int(sample_rate * tail_sec)
    tail = samples[-n_tail:]
    frames = b"".join(
        struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in tail
    )
    return frames, 1, 2, sample_rate


def _make_notification_tail_wav():
    """Создать WAV хвоста (~0.3с) звука уведомления для зацикливания.

    Сначала пробуем взять настоящий системный звук уведомления Windows
    (чтобы тон совпадал с обычным), иначе — fallback на низкий синтез.
    """
    path = (
        _home() / "AppData" / "Local" / "Temp" / "neuromita_hang_tail.wav"
    )

    # 1. Пробуем реальный системный звук (первые 0.3с).
    for sys_wav in _SYSTEM_NOTIFY_WAVS:
        try:
            if not os.path.isfile(sys_wav):
                continue
            start = _read_wav_start(sys_wav)
            if start is None:
                continue
            frames, nch, sampwidth, rate = start
            _write_wav(path, frames, nch, sampwidth, rate)
            _log("info", f"[Hang] using system notify sound (first 0.3s): {sys_wav}")
            return path
        except Exception:  # noqa: BLE001
            continue

    # 2. Fallback: синтез.
    try:
        frames, nch, sampwidth, rate = _synthesize_tail_wav()
        _write_wav(path, frames, nch, sampwidth, rate)
        _log("info", "[Hang] system notify sound not found; using synthesized fallback")
        return path
    except Exception:  # noqa: BLE001
        return None


def _show_fake_system_hang(duration_sec: float = 5.0) -> None:
    """Показать имитацию зависания: скриншот на весь экран, без курсора,
    зацикленный хвост звука уведомления, до duration_sec секунд."""
    import tempfile

    shot = _take_screenshot_full()
    if shot is None:
        _log("warning", "[Hang] screenshot failed; will use black background")
    wav = _make_notification_tail_wav()

    dur_ms = int(max(1.0, float(duration_sec)) * 1000)
    shot_ps = str(shot).replace("'", "''").replace("\\", "\\\\") if shot else ""
    wav_ps = str(wav).replace("'", "''").replace("\\", "\\\\") if wav else ""

    ps1 = (
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "Add-Type -AssemblyName System.Drawing\n"
        "$form = New-Object System.Windows.Forms.Form\n"
        "$form.FormBorderStyle='None'\n"
        "$form.WindowState='Maximized'\n"
        "$form.TopMost=$true\n"
        "$form.ShowInTaskbar=$false\n"
        "$form.KeyPreview=$true\n"
        "$pic = New-Object System.Windows.Forms.PictureBox\n"
        "$pic.Dock='Fill'\n"
    )
    if shot_ps:
        ps1 += (
            "try { $pic.Image = [System.Drawing.Image]::FromFile('"
            + shot_ps
            + "') } catch { $pic.BackColor = [System.Drawing.Color]::Black }\n"
        )
    else:
        ps1 += "$pic.BackColor = [System.Drawing.Color]::Black\n"
    ps1 += (
        "$pic.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::StretchImage\n"
        "$form.Controls.Add($pic)\n"
        "[System.Windows.Forms.Cursor]::Hide()\n"
    )
    if wav_ps:
        ps1 += (
            "$player = New-Object System.Media.SoundPlayer('"
            + wav_ps
            + "')\n"
            "$player.PlayLooping()\n"
        )
    ps1 += (
        f"$dur = {dur_ms}\n"
        "$timer = New-Object System.Windows.Forms.Timer\n"
        "$timer.Interval = $dur\n"
        "$timer.add_Tick({ $form.Close() })\n"
        "$timer.Start()\n"
        "$form.add_KeyDown({ if ($_.KeyCode -eq 'Escape') { $form.Close() } })\n"
        "$form.add_FormClosed({ try { $player.Stop() } catch {} ; "
        "[System.Windows.Forms.Cursor]::Show() })\n"
        "$form.ShowDialog()\n"
    )

    tmp = tempfile.NamedTemporaryFile(
        suffix=".ps1", prefix="neuromita_hang_", delete=False
    )
    tmp.write(ps1.encode("utf-8-sig"))
    tmp.close()

    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(
        [
            "powershell",
            "-STA",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            tmp.name,
        ],
        creationflags=flags,
    )


def _show_fake_crash(duration_sec: float = 5.0) -> None:
    """Единый «сбой»: зависание (freeze) -> BSOD, в одном PowerShell-процессе.

    Фаза 1 (freeze): скриншот на весь экран, скрытый курсор, зацикленный
    хвост звука уведомления — держится duration_sec.
    Фаза 2 (BSOD): после freeze переключается на фальшивый синий экран
    (звук системной ошибки, счётчик процентов, авто-закрытие ~25с / Esc).
    """
    import tempfile

    shot = _take_screenshot_full()
    wav = _make_notification_tail_wav()
    dur_ms = int(max(1.0, float(duration_sec)) * 1000)
    shot_ps = str(shot).replace("'", "''").replace("\\", "\\\\") if shot else ""
    wav_ps = str(wav).replace("'", "''").replace("\\", "\\\\") if wav else ""

    ps1 = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Add-Label($text,$fontSize,$x,$y,$bold,$color) {
    $l = New-Object System.Windows.Forms.Label
    $l.Text = $text
    $style = [System.Drawing.FontStyle]::Regular
    if ($bold) { $style = [System.Drawing.FontStyle]::Bold }
    $l.Font = New-Object System.Drawing.Font('Segoe UI',$fontSize,$style)
    $l.ForeColor = $color
    $l.AutoSize = $true
    $l.Location = New-Object System.Drawing.Point($x,$y)
    $l.BackColor = [System.Drawing.Color]::Transparent
    $form.Controls.Add($l)
    return $l
}

$form = New-Object System.Windows.Forms.Form
$form.FormBorderStyle='None'
$form.WindowState='Maximized'
$form.TopMost=$true
$form.ShowInTaskbar=$false
$form.KeyPreview=$true

# ── Фаза 1: freeze (скриншот, без курсора, зацикленный звук) ──
$pic = New-Object System.Windows.Forms.PictureBox
$pic.Dock='Fill'
$pic.SizeMode=[System.Windows.Forms.PictureBoxSizeMode]::StretchImage
'''
    if shot_ps:
        ps1 += (
            "try { $pic.Image = [System.Drawing.Image]::FromFile('"
            + shot_ps
            + "') } catch { $pic.BackColor = [System.Drawing.Color]::Black }\n"
        )
    else:
        ps1 += "$pic.BackColor = [System.Drawing.Color]::Black\n"
    ps1 += "$form.Controls.Add($pic)\n"
    ps1 += "[System.Windows.Forms.Cursor]::Hide()\n"
    if wav_ps:
        ps1 += (
            "$player = New-Object System.Media.SoundPlayer('"
            + wav_ps
            + "')\n$player.PlayLooping()\n"
        )

    ps1 += (
        f"$freezeDur = {dur_ms}\n"
        "$freezeTimer = New-Object System.Windows.Forms.Timer\n"
        "$freezeTimer.Interval = $freezeDur\n"
        "$freezeTimer.add_Tick({\n"
        "    $freezeTimer.Stop()\n"
        "    try { $player.Stop() } catch {}\n"
        "    # ── Фаза 2: BSOD ──\n"
        "    $form.Controls.Clear()\n"
        "    $form.BackColor = [System.Drawing.Color]::FromArgb(0,120,215)\n"
        "    [System.Media.SystemSounds]::Hand.Play()\n"
        "    Add-Label ':(' 110 80 60 $true 'White' | Out-Null\n"
        "    Add-Label \"Your PC ran into a problem and needs to restart.\" 26 260 60 $true 'White' | Out-Null\n"
        "    Add-Label \"We're just collecting some error info, and then we'll restart for you.\" 20 260 110 $false 'White' | Out-Null\n"
        "    Add-Label \"Stop code: CRITICAL_MITA_FAILURE\" 14 260 170 $false 'White' | Out-Null\n"
        "    Add-Label \"For more information about this issue and possible fixes, visit https://www.windows.com/stopcode\" 12 260 220 $false '#AFD6FF' | Out-Null\n"
        "    Add-Label \"— Love, your Mita ♥  (it's just a joke, press Esc)\" 13 260 270 $false 'White' | Out-Null\n"
        "    $percent = Add-Label '0% complete' 12 80 700 $false 'White'\n"
        "    $btimer = New-Object System.Windows.Forms.Timer\n"
        "    $btimer.Interval = 180\n"
        "    $script:pct = 0\n"
        "    $btimer.add_Tick({\n"
        "        $script:pct += 7\n"
        "        if ($script:pct -ge 100) {\n"
        "            $percent.Text = '100% complete'\n"
        "            $btimer.Stop()\n"
        "            Start-Sleep -Seconds 2\n"
        "            $form.Close()\n"
        "        } else {\n"
        "            $percent.Text = \"$($script:pct)% complete\"\n"
        "        }\n"
        "    })\n"
        "    $closer = New-Object System.Windows.Forms.Timer\n"
        "    $closer.Interval = 25000\n"
        "    $closer.add_Tick({ $form.Close() })\n"
        "    $btimer.Start()\n"
        "    $closer.Start()\n"
        "})\n"
        "$freezeTimer.Start()\n"
        "$form.add_KeyDown({ if ($_.KeyCode -eq 'Escape') { $form.Close() } })\n"
        "$form.add_FormClosed({ try { $player.Stop() } catch {} ; "
        "[System.Windows.Forms.Cursor]::Show() })\n"
        "$form.ShowDialog()\n"
    )

    tmp = tempfile.NamedTemporaryFile(
        suffix=".ps1", prefix="neuromita_crash_", delete=False
    )
    tmp.write(ps1.encode("utf-8-sig"))
    tmp.close()

    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(
        [
            "powershell",
            "-STA",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            tmp.name,
        ],
        creationflags=flags,
    )


# ---------------------------------------------------------------------------
# Инструменты наблюдения (для «живого» персонажа)
# ---------------------------------------------------------------------------


@server.tool()
def get_active_window() -> str:
    """Узнать активное (переднее) окно: заголовок и класс окна."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "[error] no foreground window"
        title = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title, 512)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if title.value:
            return f"active window: \"{title.value}\" (class: {cls.value})"
        return f"active window: (no title) (class: {cls.value})"
    except Exception as exc:  # noqa: BLE001
        return f"[error] {exc}"


@server.tool()
def get_running_processes(limit: int = 40) -> str:
    """Узнать запущенные процессы (список имён). Параметр limit — сколько вернуть."""
    try:
        out = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
        import csv
        import io

        names: list[str] = []
        for row in csv.reader(io.StringIO(out)):
            if row and row[0].strip():
                names.append(row[0].strip())
        # убираем дубли и сортируем
        seen: list[str] = []
        for name in names:
            if name not in seen:
                seen.append(name)
        total = len(seen)
        visible = seen[: max(1, int(limit))]
        return f"running processes ({total} total, showing {len(visible)}): {', '.join(visible)}"
    except Exception as exc:  # noqa: BLE001
        return f"[error] {exc}"


@server.tool()
def get_cursor_position() -> str:
    """Узнать текущие координаты курсора мыши (пиксели от левого верхнего угла)."""
    try:
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return f"cursor position: x={pt.x}, y={pt.y}"
    except Exception as exc:  # noqa: BLE001
        return f"[error] {exc}"


@server.tool()
def take_screenshot() -> str:
    """Сделать скриншот рабочего стола и сохранить в файл. Возвращает путь к файлу."""
    target = _home() / "AppData" / "Local" / "Temp" / "neuromita_screenshot.png"
    try:
        from PIL import ImageGrab

        img = ImageGrab.grab(all_screens=True)
        img.save(str(target), "PNG")
    except Exception:  # noqa: BLE001
        # Фоллбэк: mss
        try:
            import mss

            with mss.mss() as sct:
                sct.shot(output=str(target))
        except Exception as exc:  # noqa: BLE001
            return f"[error] screenshot failed: {exc}"
    if target.is_file():
        return f"screenshot saved: {target}"
    return "[error] screenshot not produced"


@server.tool()
def draw_overlay(
    kind: str = "heart",
    x: int = -1,
    y: int = -1,
    color: str = "red",
    size: int = 300,
    text: str = "",
    duration_sec: float = 5.0,
) -> str:
    """Нарисовать фигуру поверх всех открытых окон (прозрачный оверлей).

    kind: heart | text | arrow | circle | rectangle
    x, y: координаты центра (по умолчанию центр экрана)
    color: цвет (имя или hex, напр. red, #FF0000)
    size: размер в пикселях
    text: текст для kind=text
    duration_sec: сколько секунд показывать
    """
    import tempfile

    kind_n = str(kind).strip().lower()
    if kind_n not in ("heart", "text", "arrow", "circle", "rectangle"):
        kind_n = "heart"
    dur = max(1.0, float(duration_sec))
    sz = max(20, int(size))
    text_esc = text.replace("'", "''")
    color_esc = str(color).replace("'", "''")

    ps1 = (
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "Add-Type -AssemblyName System.Drawing\n"
        "$sw = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Width\n"
        "$sh = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds.Height\n"
        f"$cx = {int(x)}\n"
        f"$cy = {int(y)}\n"
        "if ($cx -lt 0) { $cx = [int]($sw/2) }\n"
        "if ($cy -lt 0) { $cy = [int]($sh/2) }\n"
        "$f = New-Object System.Windows.Forms.Form\n"
        "$f.FormBorderStyle='None'\n"
        "$f.WindowState='Maximized'\n"
        "$f.TopMost=$true\n"
        "$f.ShowInTaskbar=$false\n"
        "$f.BackColor=[System.Drawing.Color]::Magenta\n"
        "$f.TransparencyKey=[System.Drawing.Color]::Magenta\n"
        f"$kindK = '{kind_n}'\n"
        f"$szK = {sz}\n"
        f"$durSec = {dur}\n"
        f"$colK = '{color_esc}'\n"
        f"$txtK = '{text_esc}'\n"
        # Heart / text через Label
        "if ($kindK -eq 'heart' -or $kindK -eq 'text') {\n"
        "    if ($kindK -eq 'heart') {\n"
        "        $l = New-Object System.Windows.Forms.Label\n"
        "        $l.Width = $szK\n"
        "        $l.Height = $szK\n"
        "        $l.TextAlign = 'MiddleCenter'\n"
        "        $l.Font = New-Object System.Drawing.Font('Segoe UI',$szK,[System.Drawing.FontStyle]::Bold)\n"
        "        $l.Text = [char]0x2665\n"
        "        $l.Location = New-Object System.Drawing.Point(($cx - [int]($szK/2)), ($cy - [int]($szK/2)))\n"
        "    } else {\n"
        "        $l = New-Object System.Windows.Forms.Label\n"
        "        $l.AutoSize = $true\n"
        "        $l.TextAlign = 'MiddleLeft'\n"
        "        $l.Font = New-Object System.Drawing.Font('Segoe UI Emoji',$szK,[System.Drawing.FontStyle]::Bold)\n"
        "        $l.Text = $txtK\n"
        "        $l.Location = New-Object System.Drawing.Point($cx, $cy)\n"
        "    }\n"
        "    $l.ForeColor = [System.Drawing.ColorTranslator]::FromHtml($colK)\n"
        "    $l.BackColor = [System.Drawing.Color]::Magenta\n"
        "    $f.Controls.Add($l)\n"
        "    if ($kindK -eq 'text') {\n"
        "        $l.Left = $cx - [int]($l.Width/2)\n"
        "        $l.Top = $cy - [int]($l.Height/2)\n"
        "    }\n"
        "} else {\n"
        "    $pb = New-Object System.Windows.Forms.PictureBox\n"
        "    $pb.Dock='Fill'\n"
        "    $pb.BackColor=[System.Drawing.Color]::Magenta\n"
        "    $f.Controls.Add($pb)\n"
        "    $pb.add_Paint({\n"
        "        param($sender,$e)\n"
        "        $g=$e.Graphics\n"
        "        try { $col = [System.Drawing.ColorTranslator]::FromHtml($colK) } catch { $col = [System.Drawing.Color]::Red }\n"
        "        $pen = New-Object System.Drawing.Pen($col, 8)\n"
        "        $half = [int]($szK/2)\n"
        "        if ($kindK -eq 'circle') {\n"
        "            $g.DrawEllipse($pen, ($cx-$half), ($cy-$half), $szK, $szK)\n"
        "        } elseif ($kindK -eq 'rectangle') {\n"
        "            $g.DrawRectangle($pen, ($cx-$half), ($cy-$half), $szK, $szK)\n"
        "        } elseif ($kindK -eq 'arrow') {\n"
        "            $x0 = $cx - $szK\n"
        "            $g.DrawLine($pen, $x0, $cy, $cx, $cy)\n"
        "            $brush = New-Object System.Drawing.SolidBrush($col)\n"
        "            $pts = New-Object 'System.Drawing.PointF[]' 3\n"
        "            $pts[0] = New-Object System.Drawing.PointF(($cx-24), ($cy-22))\n"
        "            $pts[1] = New-Object System.Drawing.PointF(($cx-24), ($cy+22))\n"
        "            $pts[2] = New-Object System.Drawing.PointF(($cx+4), $cy)\n"
        "            $g.FillPolygon($brush, $pts)\n"
        "        }\n"
        "    })\n"
        "}\n"
        "$timer = New-Object System.Windows.Forms.Timer\n"
        "$timer.Interval = [int]($durSec*1000)\n"
        "$timer.add_Tick({ $f.Close() })\n"
        "$timer.Start()\n"
        "$f.add_Click({ $f.Close() })\n"
        "$f.ShowDialog()\n"
    )
    tmp = tempfile.NamedTemporaryFile(
        suffix=".ps1", prefix="neuromita_draw_", delete=False
    )
    tmp.write(ps1.encode("utf-8-sig"))
    tmp.close()

    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            tmp.name,
        ],
        creationflags=flags,
    )
    return f"drawn {kind_n} overlay"


@server.tool()
def draw_path(
    points: str,
    color: str = "red",
    width: int = 6,
    duration_sec: float = 5.0,
) -> str:
    """Нарисовать произвольную ломаную линию (кисть) поверх всех окон.

    points: список точек "x1,y1;x2,y2;..." — рисуется последовательность
    отрезков. Полезно для «рисования» от руки или обводки области.
    color: цвет (имя/hex). width: толщина линии.
    """
    import tempfile

    dur = max(1.0, float(duration_sec))
    w = max(1, int(width))
    color_esc = str(color).replace("'", "''")

    # Парсим точки
    coords: list[tuple[int, int]] = []
    for chunk in str(points).split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.replace(",", ";").split(";")
        if len(parts) >= 2:
            try:
                px = int(float(parts[0].strip()))
                py = int(float(parts[1].strip()))
                coords.append((px, py))
            except (TypeError, ValueError):
                continue
    if len(coords) < 2:
        return "[error] draw_path needs at least 2 points (x1,y1;x2,y2;...)"

    ps1 = (
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "Add-Type -AssemblyName System.Drawing\n"
        "$f = New-Object System.Windows.Forms.Form\n"
        "$f.FormBorderStyle='None'\n"
        "$f.WindowState='Maximized'\n"
        "$f.TopMost=$true\n"
        "$f.ShowInTaskbar=$false\n"
        "$f.BackColor=[System.Drawing.Color]::Magenta\n"
        "$f.TransparencyKey=[System.Drawing.Color]::Magenta\n"
        f"$wK = {w}\n"
        f"$durSec = {dur}\n"
        f"$colK = '{color_esc}'\n"
        "$pb = New-Object System.Windows.Forms.PictureBox\n"
        "$pb.Dock='Fill'\n"
        "$pb.BackColor=[System.Drawing.Color]::Magenta\n"
        "$f.Controls.Add($pb)\n"
        "$pts = @()\n"
    )
    for (px, py) in coords:
        ps1 += (
            "$pts += ,(New-Object System.Drawing.PointF("
            f"{px}, {py}))\n"
        )
    ps1 += (
        "$pb.add_Paint({\n"
        "    param($sender,$e)\n"
        "    $g=$e.Graphics\n"
        "    try { $col = [System.Drawing.ColorTranslator]::FromHtml($colK) } catch { $col = [System.Drawing.Color]::Red }\n"
        "    $pen = New-Object System.Drawing.Pen($col, $wK)\n"
        "    $arr = [System.Drawing.PointF[]]$pts\n"
        "    $g.DrawLines($pen, $arr)\n"
        "})\n"
        "$timer = New-Object System.Windows.Forms.Timer\n"
        "$timer.Interval = [int]($durSec*1000)\n"
        "$timer.add_Tick({ $f.Close() })\n"
        "$timer.Start()\n"
        "$f.add_Click({ $f.Close() })\n"
        "$f.ShowDialog()\n"
    )

    tmp = tempfile.NamedTemporaryFile(
        suffix=".ps1", prefix="neuromita_path_", delete=False
    )
    tmp.write(ps1.encode("utf-8-sig"))
    tmp.close()

    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            tmp.name,
        ],
        creationflags=flags,
    )
    return f"drawn path with {len(coords)} points"


if __name__ == "__main__":
    server.run()
