"""Чистые функции без зависимостей от aiogram — их легко тестировать."""
import html
import re
from datetime import datetime, timedelta
from typing import Iterable, List, Optional, Sequence, Tuple

MAX_LOOK_ITEMS = 20  # лимит вещей в образе (и защита от лимита Telegram в 100 кнопок)
NBSP = "\u00a0"
LOW_STOCK = 2  # «осталось мало» — когда в размере не больше стольких штук

# Кириллические буквы, похожие на латинские: на русской раскладке «М» и «Х» легко набрать вместо M и X.
_LOOKALIKES = str.maketrans("АВЕКМНОРСТХ", "ABEKMHOPCTX")
SIZE_RE = r"[A-Za-zА-Яа-я0-9./\-]{1,8}"
QUICK_RE = rf"^\s*№?\s*(\d{{1,9}})\s+({SIZE_RE})(?:\s+([+\-]?\d{{1,4}}))?\s*$"


def esc(value) -> str:
    """Экранирует текст для parse_mode=HTML."""
    return html.escape("" if value is None else str(value), quote=False)


def format_price(value) -> str:
    """12990 -> '12 990 ₽' (с неразрывными пробелами)."""
    if value is None:
        return "—"
    return f"{int(value):,}".replace(",", NBSP) + f"{NBSP}₽"


def truncate(text: Optional[str], limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def clamp(index: int, total: int) -> int:
    if total <= 0:
        return 0
    return max(0, min(index, total - 1))


def parse_args(data: Optional[str], prefix: str, count: int) -> Optional[Tuple[int, ...]]:
    """'tg:5:2:0' + prefix 'tg' + count 3 -> (5, 2, 0). При любой ошибке — None."""
    if not data or not data.startswith(prefix + ":"):
        return None
    parts = data[len(prefix) + 1:].split(":")
    if len(parts) != count:
        return None
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def plural(n: int, forms: Tuple[str, str, str]) -> str:
    """plural(1, ('вещь','вещи','вещей')) -> 'вещь'; 3 -> 'вещи'; 5 -> 'вещей'; 11 -> 'вещей'."""
    n = abs(int(n))
    if 11 <= n % 100 <= 14:
        return forms[2]
    last = n % 10
    if last == 1:
        return forms[0]
    if 2 <= last <= 4:
        return forms[1]
    return forms[2]


def product_caption(name: str, description: Optional[str], price, category: Optional[str] = None,
                    sizes: Optional[Sequence[Tuple[str, int]]] = None,
                    product_id: Optional[int] = None) -> str:
    lines = []
    if category:
        lines.append(f"<i>{esc(truncate(category, 40))}</i>")
    lines.append(f"<b>{esc(truncate(name, 100))}</b>")
    desc = truncate(description, 700)
    if desc:
        lines += ["", f"<blockquote>{esc(desc)}</blockquote>"]
    block = sizes_block(sizes or [])
    if block:
        lines += ["", block]
    price_line = f"<b>{format_price(price)}</b>"
    if product_id is not None:
        price_line += f"  ·  <i>арт. {product_id}</i>"
    lines += ["", price_line]
    return "\n".join(lines)


def look_text(items: Sequence[Iterable]) -> str:
    """items: (cart_id, name, price, product_id)."""
    n = len(items)
    lines = ["<b>Мой образ</b>", f"<i>{n} {plural(n, ('вещь', 'вещи', 'вещей'))}</i>", ""]
    total = 0
    for i, (_, name, price, _pid) in enumerate(items, 1):
        lines.append(f"{i} · {esc(name)} — {format_price(price)}")
        total += price or 0
    lines += ["", f"<b>Сумма образа · {format_price(total)}</b>"]
    return "\n".join(lines)


# ---------- размеры и остатки ----------

def normalize_size(raw: str) -> Optional[str]:
    """'xl' -> 'XL', кириллическая 'М' -> 'M'. Недопустимое — None."""
    size = (raw or "").strip().upper().translate(_LOOKALIKES)
    return size if re.fullmatch(r"[A-Z0-9./\-]{1,8}", size) else None


def parse_sizes(text: str) -> List[Tuple[str, int]]:
    """'S2 M3 L1' или '42:2 43:1' -> [('S',2), ('M',3), ('L',1)]. При ошибке — ValueError с понятным текстом."""
    tokens = [t for t in re.split(r"[,;\s]+", (text or "").strip()) if t]
    if not tokens:
        raise ValueError("Пусто. Пример: S2 M3 L1")
    result, seen = [], set()
    for token in tokens:
        m = re.fullmatch(r"([A-Za-zА-Яа-я]+)(\d{1,4})", token) or re.fullmatch(
            rf"({SIZE_RE})[:=](\d{{1,4}})", token)
        if not m:
            raise ValueError(f"Не понял «{token}». Пишите размер и количество слитно: S2 M3, а для чисел через двоеточие: 42:2 43:1")
        size = normalize_size(m.group(1))
        if size is None:
            raise ValueError(f"Размер «{m.group(1)}» не подходит: до 8 символов, буквы/цифры.")
        if size in seen:
            raise ValueError(f"Размер {size} указан дважды.")
        seen.add(size)
        result.append((size, int(m.group(2))))
    if len(result) > 20:
        raise ValueError("Слишком много размеров (максимум 20).")
    return result


def parse_quick(text: str) -> Optional[Tuple[int, str, int]]:
    """'12 M' -> (12, 'M', -1); '12 M 2' -> (12,'M',-2); '12 M +3' -> (12,'M',3). Не подошло — None."""
    m = re.match(QUICK_RE, text or "")
    if not m:
        return None
    size = normalize_size(m.group(2))
    if size is None:
        return None
    raw = m.group(3)
    if raw is None:
        delta = -1
    elif raw.startswith("+"):
        delta = int(raw[1:])
    else:
        delta = -abs(int(raw))
    return (int(m.group(1)), size, delta) if delta != 0 else None


def sizes_block(sizes: Sequence[Tuple[str, int]]) -> str:
    """Строка размеров для клиента: закончившиеся зачёркнуты, плюс пометка про «мало»."""
    if not sizes:
        return ""
    if all(q <= 0 for _, q in sizes):
        return "<b>Нет в наличии</b>"
    parts = [esc(s) if q > 0 else f"<s>{esc(s)}</s>" for s, q in sizes]
    lines = ["  ·  ".join(parts)]
    low = [esc(s) for s, q in sizes if 0 < q <= LOW_STOCK]
    if low:
        lines.append(f"<i>Осталось мало: {', '.join(low)}</i>")
    return "\n".join(lines)


def stock_line(sizes: Sequence[Tuple[str, int]]) -> str:
    """Для админа: 'S 2 · M 0 · L 1' или пометка, что учёта нет."""
    if not sizes:
        return "размеры не заведены"
    return "  ·  ".join(f"{esc(s)} {q}" for s, q in sizes)


def format_ts(ts: str, tz_offset: int = 0) -> str:
    """'2026-10-20 14:05:00' (UTC) -> '20.10 17:05' с учётом часового пояса."""
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S") + timedelta(hours=tz_offset)
    except (ValueError, TypeError):
        return str(ts)
    return dt.strftime("%d.%m %H:%M")
