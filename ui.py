"""Клавиатуры. Все callback_data короче 64 байт (лимит Telegram)."""
from aiogram.types import (
    InlineKeyboardButton as Btn,
    InlineKeyboardMarkup as Markup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from utils import truncate

BTN_CATALOG = "Каталог"
BTN_LOOK = "Мой образ"
BTN_ABOUT = "О бренде"


def main_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CATALOG), KeyboardButton(text=BTN_LOOK)],
            [KeyboardButton(text=BTN_ABOUT)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите раздел в меню",
    )


# ---------- клиент ----------

def _look_label(look_count: int) -> str:
    return f"{BTN_LOOK} · {look_count}" if look_count else BTN_LOOK


def catalog_kb(categories, look_count: int = 0) -> Markup:
    rows, row = [], []
    for cid, name in categories:
        row.append(Btn(text=truncate(name, 24), callback_data=f"cat:{cid}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([Btn(text=_look_label(look_count), callback_data="look")])
    return Markup(inline_keyboard=rows)


def product_kb(category_id: int, index: int, total: int, product_id: int,
               in_look: bool, look_count: int) -> Markup:
    rows = []
    if total > 1:
        rows.append([
            Btn(text="‹", callback_data=f"pg:{category_id}:{(index - 1) % total}"),
            Btn(text=f"{index + 1} / {total}", callback_data="noop"),
            Btn(text="›", callback_data=f"pg:{category_id}:{(index + 1) % total}"),
        ])
    toggle_text = "♥  В образе" if in_look else "♡  В образ"
    rows.append([Btn(text=toggle_text, callback_data=f"tg:{product_id}:{category_id}:{index}")])
    rows.append([
        Btn(text=_look_label(look_count), callback_data="look"),
        Btn(text="Каталог", callback_data="catalog"),
    ])
    return Markup(inline_keyboard=rows)


def feed_card_kb(product_id: int, in_look: bool) -> Markup:
    """Кнопка под каждой вещью в режиме ленты."""
    text = "♥  В образе" if in_look else "♡  В образ"
    return Markup(inline_keyboard=[[Btn(text=text, callback_data=f"tf:{product_id}")]])


def feed_end_kb(category_id: int, shown: int, total: int) -> Markup:
    """Последнее сообщение ленты: «показать ещё», «мой образ», «назад» (удаляет ленту)."""
    rows = []
    if shown < total:
        rows.append([Btn(text=f"Показать ещё ({total - shown})", callback_data=f"more:{category_id}:{shown}")])
    rows.append([Btn(text=BTN_LOOK, callback_data="look"), Btn(text="↩️ Назад", callback_data="fb")])
    return Markup(inline_keyboard=rows)


def look_kb(items) -> Markup:
    rows = [
        [Btn(text=f"✕  {i} · {truncate(name, 24)}", callback_data=f"rm:{pid}")]
        for i, (_cid, name, _price, pid) in enumerate(items, 1)
    ]
    rows.append([
        Btn(text="Очистить", callback_data="clr"),
        Btn(text="В каталог", callback_data="catalog"),
    ])
    return Markup(inline_keyboard=rows)


def to_catalog_kb() -> Markup:
    return Markup(inline_keyboard=[[Btn(text="В каталог", callback_data="catalog")]])


def about_kb(contact_url=None) -> Markup:
    rows = []
    if contact_url:
        rows.append([Btn(text="Написать нам", url=contact_url)])
    rows.append([Btn(text="В каталог", callback_data="catalog")])
    return Markup(inline_keyboard=rows)


# ---------- админ ----------

def admin_menu_kb() -> Markup:
    return Markup(inline_keyboard=[
        [Btn(text="➕ Категория", callback_data="a:addc"), Btn(text="🗑 Категория", callback_data="a:delc")],
        [Btn(text="➕ Товар", callback_data="a:addp"), Btn(text="🗑 Товар", callback_data="a:delp")],
        [Btn(text="📦 Остатки", callback_data="a:stock"), Btn(text="📊 Статистика", callback_data="a:stats")],
        [Btn(text="📢 Рассылка", callback_data="a:bc"), Btn(text="🚪 Выйти", callback_data="a:exit")],
    ])


def admin_cats_kb(categories, prefix: str, icon: str = "", back: str = "a:menu") -> Markup:
    rows = [
        [Btn(text=f"{icon} {truncate(name, 30)}".strip(), callback_data=f"{prefix}:{cid}")]
        for cid, name in categories
    ]
    rows.append([Btn(text="↩️ Назад", callback_data=back)])
    return Markup(inline_keyboard=rows)


def admin_products_kb(products, category_id: int) -> Markup:
    rows = [
        [Btn(text=f"🗑 {truncate(name, 30)}", callback_data=f"a:dp:{pid}:{category_id}")]
        for pid, name in products
    ]
    rows.append([Btn(text="↩️ Назад", callback_data="a:delp")])
    return Markup(inline_keyboard=rows)


def confirm_kb(yes_data: str, yes_text: str = "✅ Да") -> Markup:
    return Markup(inline_keyboard=[[
        Btn(text=yes_text, callback_data=yes_data),
        Btn(text="❌ Отмена", callback_data="a:menu"),
    ]])


def back_to_admin_kb() -> Markup:
    return Markup(inline_keyboard=[[Btn(text="↩️ Меню", callback_data="a:menu")]])


def post_product_kb() -> Markup:
    return Markup(inline_keyboard=[
        [Btn(text="➕ Ещё товар", callback_data="a:addp"), Btn(text="🛠 В меню", callback_data="a:menu")],
        [Btn(text="🚪 Выйти", callback_data="a:exit")],
    ])


def broadcast_image_kb() -> Markup:
    return Markup(inline_keyboard=[[
        Btn(text="🖼 С картинкой", callback_data="a:bc_img"),
        Btn(text="⏩ Без фото", callback_data="a:bc_skip"),
    ]])


def broadcast_confirm_kb(users_count: int) -> Markup:
    return Markup(inline_keyboard=[[
        Btn(text=f"🚀 Отправить ({users_count})", callback_data="a:bc_go"),
        Btn(text="❌ Отмена", callback_data="a:menu"),
    ]])


# ---------- остатки ----------

def stock_menu_kb() -> Markup:
    return Markup(inline_keyboard=[
        [Btn(text="🧾 Продажа / приход", callback_data="a:sl")],
        [Btn(text="📋 Все остатки", callback_data="a:st_list"), Btn(text="⚠️ Заканчивается", callback_data="a:st_low")],
        [Btn(text="✏️ Задать размеры", callback_data="a:st_set")],
        [Btn(text="📜 Журнал", callback_data="a:st_log"), Btn(text="↩️ Отменить последнее", callback_data="a:unl")],
        [Btn(text="↩️ Меню", callback_data="a:menu")],
    ])


def stock_products_kb(products, prefix: str, back: str) -> Markup:
    rows = [
        [Btn(text=f"№{pid} · {truncate(name, 28)}", callback_data=f"{prefix}:{pid}")]
        for pid, name in products
    ]
    rows.append([Btn(text="↩️ Назад", callback_data=back)])
    return Markup(inline_keyboard=rows)


def sizes_kb(product_id: int, category_id: int, sizes, mode: str, undo_log_id=None) -> Markup:
    """mode: 'sell' (нажатие списывает 1 шт.) или 'add' (прибавляет 1 шт.)."""
    action = "a:sd" if mode == "sell" else "a:sa"
    rows, row = [], []
    for size, qty in sizes:
        row.append(Btn(text=f"{size} · {qty}", callback_data=f"{action}:{product_id}:{size}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if mode == "sell":
        rows.append([Btn(text="➕ Режим прихода", callback_data=f"a:sap:{product_id}")])
    else:
        rows.append([Btn(text="➖ Режим продажи", callback_data=f"a:slp:{product_id}")])
    if undo_log_id:
        rows.append([Btn(text="↩️ Отменить последнее", callback_data=f"a:unp:{undo_log_id}")])
    rows.append([
        Btn(text="↩️ К товарам", callback_data=f"a:slc:{category_id}"),
        Btn(text="📦 Остатки", callback_data="a:stock"),
    ])
    return Markup(inline_keyboard=rows)


def undo_kb(log_id: int) -> Markup:
    return Markup(inline_keyboard=[[Btn(text="↩️ Отменить", callback_data=f"a:un:{log_id}")]])


def back_to_stock_kb() -> Markup:
    return Markup(inline_keyboard=[[Btn(text="↩️ Остатки", callback_data="a:stock")]])


def set_sizes_kb(product_id: int) -> Markup:
    return Markup(inline_keyboard=[[Btn(text="✏️ Задать размеры", callback_data=f"a:ssp:{product_id}")]])
