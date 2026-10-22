"""Рисует фирменные картинки бота: баннер для приветствия, аватарку и картинку-описание.

    pip install pillow
    python tools/make_banner.py --brand "OUTFIT" --tagline "Персональный бутик стиля"

Результат — папка assets/: banner.png (приветствие), avatar.png (для @BotFather /setuserpic),
description.png (для @BotFather /setdescriptionpic, 640x360).
Цвета: --bg (фон) и --accent (акцент), например --accent "#D6BC8A".
"""
import argparse
import os
from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    # Windows
    r"C:\Windows\Fonts\georgia.ttf", r"C:\Windows\Fonts\times.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Georgia.ttf", "/Library/Fonts/Georgia.ttf",
    # Linux
    "/usr/share/fonts/truetype/crosextra/Caladea-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
]
ITALIC_CANDIDATES = [
    r"C:\Windows\Fonts\georgiai.ttf", r"C:\Windows\Fonts\timesi.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Italic.ttf",
    "/usr/share/fonts/truetype/crosextra/Caladea-Italic.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
]


def covers(font, text):
    """True, если шрифт умеет рисовать все буквы текста (а не «квадратики»)."""
    missing = bytes(font.getmask("\U0010FFFF"))
    return all(ch.isspace() or bytes(font.getmask(ch)) != missing for ch in text)


def pick_font(candidates, size, text=""):
    """Первый существующий шрифт, в котором есть все буквы text."""
    fallback = None
    for path in candidates:
        if os.path.exists(path):
            font = ImageFont.truetype(path, size)
            if covers(font, text):
                return font
            fallback = fallback or font
    return fallback or ImageFont.load_default()


def hex_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def text_width(draw, text, font, tracking):
    return sum(draw.textlength(ch, font=font) for ch in text) + tracking * (len(text) - 1)


def draw_tracked(draw, cx, y, text, font, fill, tracking):
    """Текст по центру с разрядкой между буквами."""
    x = cx - text_width(draw, text, font, tracking) / 2
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking


def background(w, h, bg):
    top, bottom = lerp(bg, (0, 0, 0), 0.25), lerp(bg, (255, 255, 255), 0.04)
    img = Image.new("RGB", (w, h))
    px = ImageDraw.Draw(img)
    for y in range(h):
        px.line([(0, y), (w, y)], fill=lerp(top, bottom, y / h))
    return img


def ornament(draw, cx, y, accent, scale):
    half = int(120 * scale)
    gap = int(16 * scale)
    d = int(7 * scale)
    draw.line([(cx - half, y), (cx - gap, y)], fill=accent, width=max(1, int(scale)))
    draw.line([(cx + gap, y), (cx + half, y)], fill=accent, width=max(1, int(scale)))
    draw.polygon([(cx, y - d), (cx + d, y), (cx, y + d), (cx - d, y)], outline=accent)


def make_banner(brand, tagline, bg, accent, w=1280, h=720):
    img = background(w, h, bg)
    d = ImageDraw.Draw(img)
    scale = w / 1280
    # тонкая рамка
    m = int(34 * scale)
    d.rectangle([m, m, w - m, h - m], outline=lerp(bg, accent, 0.55), width=max(1, int(scale)))
    m2 = int(46 * scale)
    d.rectangle([m2, m2, w - m2, h - m2], outline=lerp(bg, accent, 0.25), width=max(1, int(scale)))

    size = int(128 * scale)
    font = pick_font(FONT_CANDIDATES, size, brand)
    # подгоняем размер, если название длинное
    while text_width(d, brand, font, size * 0.22) > w * 0.78 and size > 30:
        size -= 4
        font = pick_font(FONT_CANDIDATES, size, brand)
    top = h * 0.30 if tagline else h / 2 - size * 0.87  # без слогана — всё по центру
    draw_tracked(d, w / 2, top, brand, font, accent, size * 0.22)
    ornament(d, w / 2, int(top + size * 1.5), accent, scale)
    if tagline:
        tfont = pick_font(ITALIC_CANDIDATES, int(38 * scale), tagline)
        draw_tracked(d, w / 2, top + size * 1.5 + 36 * scale, tagline, tfont, lerp(accent, (255, 255, 255), 0.45), 2 * scale)
    return img


def make_avatar(brand, bg, accent, s=640):
    img = background(s, s, bg)
    d = ImageDraw.Draw(img)
    pad = int(s * 0.07)
    d.ellipse([pad, pad, s - pad, s - pad], outline=lerp(bg, accent, 0.6), width=2)
    d.ellipse([pad + 14, pad + 14, s - pad - 14, s - pad - 14], outline=lerp(bg, accent, 0.25), width=1)

    word = brand.strip() or "O"
    size = int(s * 0.20)
    font = pick_font(FONT_CANDIDATES, size, word)
    # вписываем слово в кружок; если слишком длинное — оставляем первую букву
    while text_width(d, word, font, size * 0.16) > s * 0.62 and size > int(s * 0.08):
        size -= 2
        font = pick_font(FONT_CANDIDATES, size, word)
    if text_width(d, word, font, size * 0.16) > s * 0.62:
        word = word[0]
        size = int(s * 0.46)
        font = pick_font(FONT_CANDIDATES, size, word)

    tracking = size * 0.16 if len(word) > 1 else 0
    bbox = d.textbbox((0, 0), word[0], font=font)
    y = (s - (bbox[3] - bbox[1])) / 2 - bbox[1]   # вертикальный центр по высоте букв
    draw_tracked(d, s / 2, y, word, font, accent, tracking)
    return img


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brand", default="OUTFIT")
    p.add_argument("--tagline", default="", help="необязательная строка под названием на баннере")
    p.add_argument("--bg", default="#151413")
    p.add_argument("--accent", default="#D6BC8A")
    p.add_argument("--out", default="assets")
    a = p.parse_args()

    os.makedirs(a.out, exist_ok=True)
    bg, accent = hex_rgb(a.bg), hex_rgb(a.accent)
    brand = a.brand.upper()
    banner = make_banner(brand, a.tagline, bg, accent)
    banner.save(os.path.join(a.out, "banner.png"), optimize=True)
    banner.resize((640, 360), Image.LANCZOS).save(os.path.join(a.out, "description.png"), optimize=True)
    make_avatar(brand, bg, accent).save(os.path.join(a.out, "avatar.png"), optimize=True)
    print(f"Готово: {a.out}/banner.png, description.png, avatar.png")


if __name__ == "__main__":
    main()
