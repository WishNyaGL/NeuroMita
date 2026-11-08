"""Тесты инструмента set_wallpaper_from_reactor (Anime Reactor).

Проверяют вспомогательные функции сервера: поиск-URL, деривацию full-URL,
парсер HTML, проверку байтов изображения. Сетевые вызовы мокаются.
"""
from __future__ import annotations

import base64
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import importlib.util as _il

_SERVER = Path(__file__).resolve().parents[3] / "scripts" / "mcp_system_interaction_server.py"
_spec = _il.spec_from_file_location("mcp_server_under_test", _SERVER)
mcp_server = _il.module_from_spec(_spec)
_spec.loader.exec_module(mcp_server)


class ReactorUrlTest(unittest.TestCase):
    def test_search_url_query_only(self):
        url = mcp_server._reactor_search_url("bleach", [])
        self.assertTrue(url.startswith("https://anime.reactor.cc/search?"))
        self.assertIn("q=bleach", url)

    def test_search_url_with_tags(self):
        url = mcp_server._reactor_search_url("bleach", ["Yoruichi"])
        self.assertIn("q=bleach", url)
        self.assertIn("tags=", url)
        self.assertIn("Yoruichi", url)

    def test_search_url_with_user(self):
        url = mcp_server._reactor_search_url("miside", [], user="rita")
        self.assertIn("user=rita", url)


class ReactorAbsTest(unittest.TestCase):
    def test_protocol_relative(self):
        self.assertEqual(
            mcp_server._reactor_abs("//img2.reactor.cc/pics/post/full/a.jpg"),
            "https://img2.reactor.cc/pics/post/full/a.jpg",
        )

    def test_root_relative(self):
        self.assertEqual(
            mcp_server._reactor_abs("/post/123"),
            "https://anime.reactor.cc/post/123",
        )

    def test_absolute_unchanged(self):
        self.assertEqual(
            mcp_server._reactor_abs("https://x/y.png"), "https://x/y.png"
        )


class ReactorDeriveTest(unittest.TestCase):
    def test_derive_full_from_thumb(self):
        thumb = "//img2.reactor.cc/pics/post/a.jpeg"
        self.assertEqual(
            mcp_server._reactor_derive_full(thumb),
            "https://img2.reactor.cc/pics/post/full/a.jpeg",
        )

    def test_derive_full_already_full(self):
        full = "https://img2.reactor.cc/pics/post/full/a.jpeg"
        self.assertEqual(mcp_server._reactor_derive_full(full), full)

    def test_derive_full_no_match(self):
        self.assertEqual(mcp_server._reactor_derive_full("https://other/x"), "")


class ReactorParserTest(unittest.TestCase):
    HTML = """
    <html><body>
      <div class="post_content"><div><div class="image">
        <a href="https://img10.reactor.cc/pics/post/full/one.jpeg" class="prettyPhotoLink" rel="prettyPhoto">
          <img src="https://img10.reactor.cc/pics/post/one.jpeg"></a>
      </div></div></div>
      <div class="post_content"><div><div class="image">
        <a href="https://img10.reactor.cc/pics/post/full/two.png" class="prettyPhotoLink" rel="prettyPhoto">
          <img src="https://img10.reactor.cc/pics/post/two.png"></a>
      </div></div></div>
      <a href="/search/bleach/2?tags=Yoruichi%2C+">2</a>
      <a href="/search/mita/3">3</a>
      <a href="/search/Mita+gif">Mita gif</a>
      <a href="/post/999">post</a>
    </body></html>
    """

    def test_parses_full_images_and_thumbs(self):
        p = mcp_server._ReactorLinkParser()
        p.feed(self.HTML)
        self.assertIn("https://img10.reactor.cc/pics/post/full/one.jpeg", p.full_images)
        self.assertIn("https://img10.reactor.cc/pics/post/full/two.png", p.full_images)
        self.assertIn("https://img10.reactor.cc/pics/post/one.jpeg", p.thumbs)
        # Пост-ссылка не должна попасть в full_images.
        self.assertFalse(any("post/999" in f for f in p.full_images))

    def test_parses_pagination_real_format(self):
        p = mcp_server._ReactorLinkParser()
        p.feed(self.HTML)
        # Должны попасть только реальные страницы с номером.
        self.assertTrue(any("bleach/2" in pg for pg in p.pages))
        self.assertTrue(any("mita/3" in pg for pg in p.pages))
        # «также ищут» (без номера страницы) НЕ должны попасть.
        self.assertFalse(any("Mita+gif" in pg for pg in p.pages))

    def test_avatar_holder_is_ignored(self):
        """Аватарки из uhead/avatar_holder не должны попасть в full_images.

        Воспроизводит реальный кейс: аватарка (маленькая картинка в шапке
        поста) НЕ должна быть выбрана вместо поста.
        """
        html = """
        <html><body>
          <div class="postContainer"><div class="article post-normal">
            <div class="post_top"><div class="uhead">
              <div class="avatar_holder" title="user">
                <a href="https://img10.reactor.cc/pics/post/full/avatar_small.jpeg"
                   class="prettyPhotoLink" rel="prettyPhoto">
                  <img src="https://img10.reactor.cc/pics/post/avatar_small.jpeg"></a>
              </div>
            </div></div>
            <div class="post_content"><div><div class="image">
              <a href="https://img10.reactor.cc/pics/post/full/real_post.jpeg"
                 class="prettyPhotoLink" rel="prettyPhoto">
                <img src="https://img10.reactor.cc/pics/post/real_post.jpeg"></a>
            </div></div></div>
          </div></div>
        </body></html>
        """
        p = mcp_server._ReactorLinkParser()
        p.feed(html)
        # В full_images должен попасть ТОЛЬКО пост, не аватарка.
        self.assertIn("https://img10.reactor.cc/pics/post/full/real_post.jpeg", p.full_images)
        self.assertNotIn(
            "https://img10.reactor.cc/pics/post/full/avatar_small.jpeg",
            p.full_images,
        )
        # Миниатюры: только из div.image (реальный пост).
        self.assertNotIn(
            "https://img10.reactor.cc/pics/post/avatar_small.jpeg", p.thumbs
        )
        self.assertIn(
            "https://img10.reactor.cc/pics/post/real_post.jpeg", p.thumbs
        )


class ReactorDecodeUrlTest(unittest.TestCase):
    def test_decodes_cyrillic_path(self):
        url = (
            "https://img10.reactor.cc/pics/post/full/"
            "generatornaya-%D0%BD%D0%B5%D0%B9%D1%80%D0%BE%D0%B0%D1%80%D1%82-8798979.jpeg"
        )
        decoded = mcp_server._reactor_decode_url(url)
        self.assertIn("нейроарт", decoded)
        # Схема/хост/расширение не тронуты.
        self.assertTrue(decoded.startswith("https://img10.reactor.cc/"))
        self.assertTrue(decoded.endswith(".jpeg"))

    def test_does_not_break_plain_url(self):
        url = "https://img2.reactor.cc/pics/post/full/x.jpeg"
        self.assertEqual(mcp_server._reactor_decode_url(url), url)


class ReactorImageBytesTest(unittest.TestCase):
    def test_jpeg(self):
        self.assertTrue(mcp_server._reactor_is_image_bytes(b"\xff\xd8\xff\xe0rest"))

    def test_png(self):
        self.assertTrue(mcp_server._reactor_is_image_bytes(b"\x89PNG\r\n\x1a\nmore"))

    def test_gif(self):
        self.assertTrue(mcp_server._reactor_is_image_bytes(b"GIF89a..."))

    def test_webp(self):
        self.assertTrue(mcp_server._reactor_is_image_bytes(b"RIFF....WEBP"))

    def test_not_image(self):
        self.assertFalse(mcp_server._reactor_is_image_bytes(b"plain text"))
        self.assertFalse(mcp_server._reactor_is_image_bytes(b""))


class ReactorRealHtmlTest(unittest.TestCase):
    """Проверка парсера на реальных сохранённых страницах Anime Reactor."""

    TEMP = Path(r"C:\PROGI\PROJECTS\temp")

    def _html(self, name):
        p = self.TEMP / name
        if not p.exists():
            self.skipTest(f"файл {name} отсутствует")
        return p.read_text(encoding="utf-8", errors="replace")

    def test_bleach_full_links_and_pages(self):
        s = self._html("bleach.htm")
        p = mcp_server._ReactorLinkParser()
        p.feed(s)
        self.assertGreater(len(p.full_images), 0)
        # Все full-ссылки абсолютные https и содержат /full/.
        for u in p.full_images:
            self.assertTrue(u.startswith("https://"), u)
            self.assertIn("/full/", u)
        # Реальная пагинация /search/bleach/<N>.
        pages = [u for u in p.pages if "bleach/" in u]
        self.assertGreater(len(pages), 0)

    def test_mita_full_links_and_pages(self):
        s = self._html("mita.htm")
        p = mcp_server._ReactorLinkParser()
        p.feed(s)
        self.assertGreater(len(p.full_images), 0)
        pages = [u for u in p.pages if "/search/mita/" in u.lower()]
        self.assertGreater(len(pages), 0)

    def test_openfull_matches_anchor_full(self):
        # В раскрытом виде #fullResImage.src переписан на локальный файл,
        # но полноразмерный URL есть в href у .prettyPhotoLink. Проверяем,
        # что href-ссылки присутствуют и корректны.
        s = self._html("mita-openfull.htm")
        p = mcp_server._ReactorLinkParser()
        p.feed(s)
        self.assertGreater(len(p.full_images), 0)


class ReactorPrioritizeTest(unittest.TestCase):
    def test_exact_filename_first(self):
        candidates = [
            "https://img10.reactor.cc/pics/post/full/Anime-Ero-Cosplay-9535047.jpeg",
            "https://img10.reactor.cc/pics/post/full/Shihouin-Yoruichi-Bleach-Anime-9348536.jpeg",
            "https://img10.reactor.cc/pics/post/full/Umeko-J-anime-cosplay-9535048.jpeg",
        ]
        ordered = mcp_server._reactor_prioritize_candidates(candidates, "bleach", ["Yoruichi"])
        # Первый должен быть точным (Yoruichi/Bleach в имени).
        self.assertEqual(
            ordered[0],
            "https://img10.reactor.cc/pics/post/full/Shihouin-Yoruichi-Bleach-Anime-9348536.jpeg",
        )

    def test_fallback_when_no_exact(self):
        candidates = [
            "https://img10.reactor.cc/pics/post/full/Anime-Ero-9535047.jpeg",
            "https://img10.reactor.cc/pics/post/full/Something-else-1.jpeg",
        ]
        ordered = mcp_server._reactor_prioritize_candidates(candidates, "bleach", ["Yoruichi"])
        # Ни одного точного — порядок не меняется (stable).
        self.assertEqual(set(ordered), set(candidates))
        self.assertEqual(len(ordered), 2)

    def test_cyrillic_tag_match(self):
        candidates = [
            "https://img10.reactor.cc/pics/post/full/Anime-Ero-9535047.jpeg",
            "https://img10.reactor.cc/pics/post/full/"
            "generatornaya-%D0%BD%D0%B5%D0%B9%D1%80%D0%BE%D0%B0%D1%80%D1%82-8798979.jpeg",
        ]
        ordered = mcp_server._reactor_prioritize_candidates(candidates, "мита", ["нейроарт"])
        # Точный — где в имени есть «нейроарт».
        self.assertTrue(ordered[0].endswith("-8798979.jpeg"))

    def test_normalize_token(self):
        self.assertEqual(mcp_server._reactor_normalize_token("Yoruichi"), "yoruichi")
        self.assertEqual(mcp_server._reactor_normalize_token("MiSide"), "miside")
        self.assertNotEqual(mcp_server._reactor_normalize_token("Мита"), "")


class ReactorFindTest(unittest.TestCase):
    def test_find_full_url_uses_full_images(self):
        html = (
            '<div class="post_content"><div><div class="image">'
            '<a href="//img2.reactor.cc/pics/post/full/x.jpg" class="prettyPhotoLink">'
            '<img src="//img2.reactor.cc/pics/post/x.jpg"></a>'
            "</div></div></div>"
        )
        with patch.object(mcp_server, "_reactor_fetch", return_value=html):
            with patch.object(
                mcp_server, "_reactor_download",
                return_value=(b"\xff\xd8\xffjpg", "https://img2.reactor.cc/pics/post/full/x.jpg"),
            ):
                url, debug = mcp_server._reactor_find_full_url("bleach", [], "", False)
        self.assertEqual(url, "https://img2.reactor.cc/pics/post/full/x.jpg")
        self.assertIn("search_url", debug)

    def test_find_returns_none_on_empty(self):
        with patch.object(mcp_server, "_reactor_fetch", return_value="<html></html>"):
            url, debug = mcp_server._reactor_find_full_url("zzz", [], "", False)
        self.assertIsNone(url)
        self.assertIn("no_candidates", debug["errors"])

    def test_find_simplifies_when_first_empty(self):
        """Если первый вариант пуст — пробуем упрощённый (без тегов)."""
        empty_html = "<html></html>"
        good_html = (
            '<div class="post_content"><div><div class="image">'
            '<a href="https://img2.reactor.cc/pics/post/full/x.jpg" '
            'class="prettyPhotoLink"><img src="https://img2.reactor.cc/pics/post/x.jpg"></a>'
            "</div></div></div>"
        )
        # Первый fetch (query+tags) — пусто; второй (query без тегов) — есть.
        calls = {"n": 0}

        def fake_fetch(url):
            calls["n"] += 1
            return empty_html if calls["n"] == 1 else good_html

        with patch.object(mcp_server, "_reactor_fetch", side_effect=fake_fetch):
            with patch.object(
                mcp_server, "_reactor_download",
                return_value=(b"\xff\xd8\xffjpg", "https://img2.reactor.cc/pics/post/full/x.jpg"),
            ):
                url, debug = mcp_server._reactor_find_full_url(
                    "bleach", ["Yoruichi"], "", False
                )
        self.assertEqual(url, "https://img2.reactor.cc/pics/post/full/x.jpg")
        # Должно быть не менее 2 вариантов.
        self.assertGreaterEqual(len(debug["variants"]), 2)

    def test_simplify_query_variants(self):
        variants = mcp_server._reactor_simplify_query("bleach", ["Yoruichi"])
        # (bleach+tags), (bleach), (tags)
        self.assertEqual(len(variants), 3)
        self.assertEqual(variants[0], ("bleach", ["Yoruichi"]))
        self.assertEqual(variants[1], ("bleach", []))
        self.assertEqual(variants[2], ("", ["Yoruichi"]))


class ToolResultJsonTest(unittest.TestCase):
    def test_success_result_shape(self):
        payload = {
            "success": True,
            "source": "Anime Reactor",
            "query": "bleach",
            "image_url": "https://img2.reactor.cc/pics/post/full/x.jpg",
            "wallpaper_set": True,
        }
        text = json.dumps(payload, ensure_ascii=False)
        parsed = json.loads(text)
        self.assertTrue(parsed["success"])
        self.assertEqual(parsed["source"], "Anime Reactor")


if __name__ == "__main__":
    unittest.main()
