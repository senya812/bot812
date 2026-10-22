import unittest

from config import DEFAULT_ABOUT, DEFAULT_TAGLINE, load_config, normalize_contact, parse_admin_ids
from utils import (
    MAX_LOOK_ITEMS, clamp, esc, format_price, format_ts, look_text, normalize_size, parse_args, parse_quick,
    parse_sizes, plural, product_caption, sizes_block, stock_line, truncate,
)


class TestFormatting(unittest.TestCase):
    def test_price(self):
        self.assertEqual(format_price(12990), "12\u00a0990\u00a0₽")
        self.assertEqual(format_price(0), "0\u00a0₽")
        self.assertEqual(format_price(1500000), "1\u00a0500\u00a0000\u00a0₽")
        self.assertEqual(format_price(None), "—")

    def test_esc(self):
        self.assertEqual(esc("a<b>&c"), "a&lt;b&gt;&amp;c")
        self.assertEqual(esc(None), "")
        self.assertEqual(esc("T_shirt *x*"), "T_shirt *x*")

    def test_truncate(self):
        self.assertEqual(truncate("abc", 5), "abc")
        self.assertEqual(truncate("abcdefgh", 5), "abcd…")
        self.assertEqual(truncate(None, 5), "")

    def test_clamp(self):
        self.assertEqual(clamp(5, 3), 2)
        self.assertEqual(clamp(-1, 3), 0)
        self.assertEqual(clamp(1, 0), 0)


class TestParseArgs(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(parse_args("tg:5:2:0", "tg", 3), (5, 2, 0))
        self.assertEqual(parse_args("a:dc:7", "a:dc", 1), (7,))

    def test_bad_input_returns_none(self):
        self.assertIsNone(parse_args("tg:5:2", "tg", 3))
        self.assertIsNone(parse_args("tg:x:2:0", "tg", 3))
        self.assertIsNone(parse_args("cat:1", "pg", 1))
        self.assertIsNone(parse_args(None, "pg", 1))
        self.assertIsNone(parse_args("a:dcy:1", "a:dc", 1))  # префиксы не путаются


class TestTexts(unittest.TestCase):
    def test_caption_escapes_html(self):
        text = product_caption("Куртка <Zara> & Co", "тёплая_*куртка*", 4990)
        self.assertIn("&lt;Zara&gt; &amp; Co", text)
        self.assertIn("4\u00a0990\u00a0₽", text)
        self.assertNotIn("<Zara>", text)

    def test_caption_without_description(self):
        text = product_caption("A", "", 1)
        self.assertNotIn("\n\n\n", text)
        self.assertNotIn("blockquote", text)

    def test_caption_layout(self):
        text = product_caption("Парка", "тёплая", 4990, "Куртки")
        self.assertEqual(
            text,
            "<i>Куртки</i>\n<b>Парка</b>\n\n<blockquote>тёплая</blockquote>\n\n<b>4\u00a0990\u00a0₽</b>",
        )

    def test_caption_escapes_category(self):
        self.assertIn("&lt;x&gt;", product_caption("A", "d", 1, "<x>"))

    def test_caption_fits_telegram_limit(self):
        self.assertLess(len(product_caption("N" * 500, "D" * 5000, 10 ** 6)), 1024)

    def test_look_text_total(self):
        items = [(1, "Парка", 5000, 10), (2, "Шарф", 1500, 11)]
        text = look_text(items)
        self.assertIn("1 · Парка — 5\u00a0000\u00a0₽", text)
        self.assertIn("2 · Шарф — 1\u00a0500\u00a0₽", text)
        self.assertIn("<b>Сумма образа · 6\u00a0500\u00a0₽</b>", text)
        self.assertIn("<i>2 вещи</i>", text)

    def test_look_text_handles_missing_price(self):
        self.assertIn("1\u00a0000\u00a0₽", look_text([(1, "A", None, 1), (2, "B", 1000, 2)]))

    def test_max_look_items_fits_button_limit(self):
        self.assertLessEqual(MAX_LOOK_ITEMS + 1, 100)  # Telegram: максимум 100 кнопок


class TestSizes(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_size(" xl "), "XL")
        self.assertEqual(normalize_size("М"), "M")        # кириллическая М
        self.assertEqual(normalize_size("ХL"), "XL")      # кириллическая Х + латинская L
        self.assertEqual(normalize_size("42"), "42")
        self.assertEqual(normalize_size("2XL"), "2XL")
        for bad in ("", "toolongsize", "S M", "Ю", "<b>"):
            self.assertIsNone(normalize_size(bad), bad)

    def test_parse_sizes_ok(self):
        self.assertEqual(parse_sizes("S2 M3 xl10"), [("S", 2), ("M", 3), ("XL", 10)])
        self.assertEqual(parse_sizes("42:2, 43:1"), [("42", 2), ("43", 1)])
        self.assertEqual(parse_sizes("2XL:4 ХL0"), [("2XL", 4), ("XL", 0)])
        self.assertEqual(parse_sizes("М2 L1"), [("M", 2), ("L", 1)])
        self.assertEqual(parse_sizes("S=1;M=2"), [("S", 1), ("M", 2)])

    def test_parse_sizes_errors(self):
        for bad in ("", "   ", "S", "S M", "42 2", "S2 S3", "S-1", "S99999", "<b>2"):
            with self.assertRaises(ValueError, msg=bad):
                parse_sizes(bad)
        with self.assertRaises(ValueError):
            parse_sizes(" ".join(f"A{i}:1" for i in range(21)))

    def test_parse_quick(self):
        self.assertEqual(parse_quick("12 M"), (12, "M", -1))
        self.assertEqual(parse_quick("12 м 2"), (12, "M", -2))
        self.assertEqual(parse_quick("№12 xl -3"), (12, "XL", -3))
        self.assertEqual(parse_quick("12 M +3"), (12, "M", 3))
        self.assertEqual(parse_quick("  7   42  "), (7, "42", -1))
        for bad in ("12", "M 12", "12 M 0", "12 M +0", "привет", "12 M extra", "12 toolongsize"):
            self.assertIsNone(parse_quick(bad), bad)

    def test_quick_regex_gate_matches_parser(self):
        import re
        from utils import QUICK_RE
        for text in ("12 M", "12 M 2", "№5 XL +1", "привет", "12", "12 M extra"):
            self.assertEqual(bool(re.match(QUICK_RE, text)), parse_quick(text) is not None, text)

    def test_sizes_block(self):
        self.assertEqual(sizes_block([]), "")
        self.assertEqual(sizes_block([("S", 5), ("M", 5)]), "S  ·  M")
        self.assertEqual(sizes_block([("S", 5), ("M", 1), ("L", 0)]),
                         "S  ·  M  ·  <s>L</s>\n<i>Осталось мало: M</i>")
        self.assertEqual(sizes_block([("S", 0), ("M", 0)]), "<b>Нет в наличии</b>")

    def test_stock_line(self):
        self.assertEqual(stock_line([("S", 2), ("M", 0)]), "S 2  ·  M 0")
        self.assertEqual(stock_line([]), "размеры не заведены")

    def test_caption_with_sizes_and_article(self):
        text = product_caption("Парка", "тёплая", 4990, "Куртки", sizes=[("S", 3), ("M", 0)], product_id=12)
        self.assertEqual(
            text,
            "<i>Куртки</i>\n<b>Парка</b>\n\n<blockquote>тёплая</blockquote>\n\n"
            "S  ·  <s>M</s>\n\n<b>4\u00a0990\u00a0₽</b>  ·  <i>арт. 12</i>",
        )

    def test_caption_sold_out(self):
        self.assertIn("<b>Нет в наличии</b>", product_caption("A", "d", 1, sizes=[("S", 0)]))

    def test_format_ts(self):
        self.assertEqual(format_ts("2026-10-20 14:05:00", 3), "20.10 17:05")
        self.assertEqual(format_ts("2026-10-20 23:30:00", 3), "21.10 02:30")
        self.assertEqual(format_ts("garbage", 3), "garbage")


class TestPlural(unittest.TestCase):
    def test_forms(self):
        forms = ("вещь", "вещи", "вещей")
        expected = {1: "вещь", 2: "вещи", 4: "вещи", 5: "вещей", 11: "вещей", 12: "вещей",
                    14: "вещей", 20: "вещей", 21: "вещь", 22: "вещи", 101: "вещь", 111: "вещей"}
        for n, word in expected.items():
            self.assertEqual(plural(n, forms), word, n)


class TestConfig(unittest.TestCase):
    def test_ok(self):
        cfg = load_config({"BOT_TOKEN": " 1:abc ", "ADMIN_ID": "42", "PROXY_URL": ""})
        self.assertEqual((cfg.token, cfg.admin_id, cfg.proxy, cfg.welcome_photo), ("1:abc", 42, None, None))

    def test_brand_defaults(self):
        brand = load_config({"BOT_TOKEN": "1:abc", "ADMIN_ID": "1"}).brand
        self.assertEqual((brand.name, brand.tagline, brand.about, brand.contact_url),
                         ("Outfit", DEFAULT_TAGLINE, DEFAULT_ABOUT, None))

    def test_brand_from_env(self):
        brand = load_config({"BOT_TOKEN": "1:abc", "ADMIN_ID": "1", "BRAND_NAME": " Atelier 9 ",
                             "BRAND_TAGLINE": "Одежда с характером", "BRAND_ABOUT": "Первая строка\\nВторая",
                             "CONTACT_URL": "@atelier9"}).brand
        self.assertEqual(brand.name, "Atelier 9")
        self.assertEqual(brand.tagline, "Одежда с характером")
        self.assertEqual(brand.about, "Первая строка\nВторая")
        self.assertEqual(brand.contact_url, "https://t.me/atelier9")

    def test_normalize_contact(self):
        self.assertEqual(normalize_contact("https://example.com/x"), "https://example.com/x")
        self.assertEqual(normalize_contact("tg://resolve?domain=shop"), "tg://resolve?domain=shop")
        self.assertEqual(normalize_contact("@shop"), "https://t.me/shop")
        for bad in ("", "   ", "@", "shop", "javascript:alert(1)", "t.me/shop"):
            self.assertIsNone(normalize_contact(bad), bad)

    def test_parse_admin_ids(self):
        self.assertEqual(parse_admin_ids("42"), (42,))
        self.assertEqual(parse_admin_ids("111, 222;333 222"), (111, 222, 333))   # дубли убираются
        for bad in ("", "  ", "abc", "1,x", "-5", "1.5", "１２"):
            self.assertEqual(parse_admin_ids(bad), (), bad)

    def test_several_admins_and_timezone(self):
        cfg = load_config({"BOT_TOKEN": "1:abc", "ADMIN_ID": "111, 222", "TZ_OFFSET": "-5"})
        self.assertEqual(cfg.admin_ids, (111, 222)); self.assertEqual(cfg.admin_id, 111); self.assertEqual(cfg.tz_offset, -5)
        self.assertEqual(load_config({"BOT_TOKEN": "1:abc", "ADMIN_ID": "1"}).tz_offset, 3)

    def test_bad_timezone(self):
        for bad in ("x", "15", "-13", "2.5"):
            with self.assertRaises(SystemExit, msg=bad):
                load_config({"BOT_TOKEN": "1:abc", "ADMIN_ID": "1", "TZ_OFFSET": bad})

    def test_catalog_mode(self):
        base = {"BOT_TOKEN": "1:abc", "ADMIN_ID": "1"}
        self.assertEqual(load_config(base).catalog_mode, "carousel")
        self.assertEqual(load_config({**base, "CATALOG_MODE": " FEED "}).catalog_mode, "feed")
        self.assertEqual(load_config({**base, "CATALOG_MODE": ""}).catalog_mode, "carousel")
        with self.assertRaises(SystemExit):
            load_config({**base, "CATALOG_MODE": "grid"})

    def test_missing_token(self):
        with self.assertRaises(SystemExit):
            load_config({"ADMIN_ID": "42"})

    def test_bad_admin_id(self):
        for bad in ("", "abc", "12.5", "-1"):
            with self.assertRaises(SystemExit, msg=bad):
                load_config({"BOT_TOKEN": "1:abc", "ADMIN_ID": bad})


if __name__ == "__main__":
    unittest.main()
