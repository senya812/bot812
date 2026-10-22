"""Учёт размеров для админов: быстрая продажа сообщением, кнопки, остатки, журнал, отмена.

Роутер подключается в main.py с фильтром «только админы» и ДО клиентского роутера —
иначе клиентская «заглушка» перехватила бы сообщения вида «12 M».
"""
import logging
from typing import Sequence, Tuple

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import database as db
import ui
from messaging import msg_of, show_text
from utils import (
    LOW_STOCK, QUICK_RE, esc, format_ts, normalize_size, parse_args, parse_quick, parse_sizes, stock_line,
    truncate,
)

log = logging.getLogger(__name__)
router = Router(name="stock")

QUICK_HELP = (
    "Быстрая продажа — просто напишите сообщение боту:\n"
    "<code>12 M</code> — продан размер M у товара №12\n"
    "<code>12 M 2</code> — продано 2 шт. · <code>12 M +3</code> — приход 3 шт."
)


class StockStates(StatesGroup):
    setting = State()


def _minus(n: int) -> str:
    return f"{n:+d}".replace("-", "−")


async def notify_admins(bot, admin_ids: Sequence[int], actor_id: int, text: str) -> None:
    """Сообщает остальным админам (не тому, кто сам это сделал)."""
    for admin_id in admin_ids:
        if admin_id == actor_id:
            continue
        try:
            await bot.send_message(chat_id=admin_id, text=text)
        except TelegramAPIError as e:
            log.info("Не удалось уведомить админа %s: %s", admin_id, e)


async def apply_change(bot, actor, product_id: int, size: str, delta: int,
                       admin_ids: Sequence[int]) -> Tuple[str, "int | None"]:
    """Общая логика продажи/прихода. Возвращает (текст ответа, id записи журнала или None)."""
    db.touch_admin(actor.id, actor.first_name or actor.username or str(actor.id))
    details = db.get_product_details(product_id)
    if details is None:
        return f"Товар №{product_id} не найден.", None
    name = details[1]
    stock = dict(db.get_stock(product_id))
    if not stock:
        return (f"У товара №{product_id} «{esc(name)}» не заведены размеры.\n"
                "Остатки → «Задать размеры»."), None
    if size not in stock:
        return f"У товара №{product_id} «{esc(name)}» нет размера {esc(size)}. Есть: {esc(', '.join(stock))}.", None

    status, qty, log_id = db.change_stock(product_id, size, delta, actor.id)
    if status == "insufficient":
        return f"«{esc(name)}» · {esc(size)}: на складе {qty} шт., списать {-delta} нельзя.", None

    text = f"<b>{esc(name)}</b> · {esc(size)}: {_minus(delta)} → осталось <b>{qty}</b>"
    if qty == 0 and delta < 0:
        text += "\n⚠️ Этот размер закончился"
        who = actor.first_name or str(actor.id)
        await notify_admins(bot, admin_ids, actor.id,
                            f"⚠️ «{name}» (№{product_id}): размер {size} закончился. Отметил(а): {who}.")
    return text, log_id


# ---------- быстрая продажа сообщением ----------

@router.message(StateFilter(None), F.text.regexp(QUICK_RE))
async def quick_change(m: Message, admin_ids: Sequence[int] = ()):
    parsed = parse_quick(m.text)
    if parsed is None:
        return
    product_id, size, delta = parsed
    text, log_id = await apply_change(m.bot, m.from_user, product_id, size, delta, admin_ids)
    await m.answer(text, reply_markup=ui.undo_kb(log_id) if log_id else None)


# ---------- главная страница раздела ----------

def _low_lines(rows) -> str:
    return "\n".join(
        f"№{pid} {esc(truncate(name, 28))} · {esc(size)} — {qty if qty else 'нет'}" for pid, name, size, qty in rows
    )


def home_text() -> str:
    parts = ["<b>Остатки</b>", "", QUICK_HELP, ""]
    low = db.low_stock(LOW_STOCK, 8)
    parts.append("<b>Заканчивается</b>\n" + _low_lines(low) if low else "Всё в достатке.")
    return "\n".join(parts)


@router.callback_query(F.data == "a:stock")
async def cb_stock(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_text(c, home_text(), ui.stock_menu_kb())
    await c.answer()


@router.callback_query(F.data == "a:st_low")
async def cb_low(c: CallbackQuery):
    rows = db.low_stock(LOW_STOCK, 40)
    text = ("<b>Заканчивается</b> (осталось " + f"{LOW_STOCK} и меньше)\n\n" + _low_lines(rows)) if rows \
        else "Всё в достатке — нет размеров, которые заканчиваются."
    await show_text(c, text, ui.back_to_stock_kb())
    await c.answer()


# ---------- все остатки по категориям ----------

@router.callback_query(F.data == "a:st_list")
async def cb_list(c: CallbackQuery):
    cats = db.get_categories()
    if not cats:
        await c.answer("Категорий нет!", show_alert=True)
        return
    await show_text(c, "📋 Выберите категорию:", ui.admin_cats_kb(cats, "a:stl", back="a:stock"))
    await c.answer()


@router.callback_query(F.data.startswith("a:stl:"))
async def cb_list_category(c: CallbackQuery):
    args = parse_args(c.data, "a:stl", 1)
    name = db.get_category(args[0]) if args else None
    if name is None:
        await c.answer("Категория не найдена", show_alert=True)
        return
    lines = [f"<b>{esc(name)}</b>", ""]
    items = db.category_stock(args[0])
    if not items:
        lines.append("Пока нет товаров.")
    for pid, pname, sizes in items:
        lines.append(f"№{pid} {esc(truncate(pname, 30))}\n      {stock_line(sizes)}")
    text = "\n".join(lines)
    if len(text) > 3800:
        text = text[:3800].rsplit("\n", 1)[0] + "\n…"
    await show_text(c, text, ui.admin_cats_kb(db.get_categories(), "a:stl", back="a:stock"))
    await c.answer()


# ---------- продажа / приход кнопками ----------

@router.callback_query(F.data == "a:sl")
async def cb_sell_start(c: CallbackQuery):
    cats = db.get_categories()
    if not cats:
        await c.answer("Категорий нет!", show_alert=True)
        return
    await show_text(c, "🧾 Выберите категорию:", ui.admin_cats_kb(cats, "a:slc", back="a:stock"))
    await c.answer()


@router.callback_query(F.data.startswith("a:slc:"))
async def cb_sell_category(c: CallbackQuery):
    args = parse_args(c.data, "a:slc", 1)
    name = db.get_category(args[0]) if args else None
    if name is None:
        await c.answer("Категория не найдена", show_alert=True)
        return
    products = db.get_products_by_category(args[0])
    if not products:
        await c.answer("В категории нет товаров", show_alert=True)
        return
    await show_text(c, f"<b>{esc(name)}</b>\nВыберите товар:",
                    ui.stock_products_kb(products, "a:slp", back="a:sl"))
    await c.answer()


async def render_sizes(c: CallbackQuery, product_id: int, mode: str, note: str = "", undo_id=None) -> None:
    details = db.get_product_details(product_id)
    if details is None:
        await c.answer("Товар не найден", show_alert=True)
        return
    category_id, name = details[0], details[1]
    sizes = db.get_stock(product_id)
    if not sizes:
        await show_text(
            c, f"<b>{esc(name)}</b> · №{product_id}\n\nРазмеры не заведены — учёт для этого товара не ведётся.",
            ui.set_sizes_kb(product_id),
        )
        return
    hint = ("Нажмите размер — спишется 1 шт. (продажа)." if mode == "sell"
            else "Нажмите размер — добавится 1 шт. (приход).")
    text = f"<b>{esc(name)}</b> · №{product_id}\n{stock_line(sizes)}\n\n{hint}"
    if note:
        text = f"{note}\n\n{text}"
    await show_text(c, text, ui.sizes_kb(product_id, category_id, sizes, mode, undo_id))


@router.callback_query(F.data.startswith("a:slp:"))
async def cb_sizes_sell(c: CallbackQuery):
    args = parse_args(c.data, "a:slp", 1)
    if args:
        await render_sizes(c, args[0], "sell")
    await c.answer()


@router.callback_query(F.data.startswith("a:sap:"))
async def cb_sizes_add(c: CallbackQuery):
    args = parse_args(c.data, "a:sap", 1)
    if args:
        await render_sizes(c, args[0], "add")
    await c.answer()


def _parse_size_cb(data: str):
    """'a:sd:12:M' -> (12, 'M')"""
    parts = (data or "").split(":", 3)
    if len(parts) != 4 or not parts[2].isdigit():
        return None
    size = normalize_size(parts[3])
    return (int(parts[2]), size) if size else None


async def _tap(c: CallbackQuery, delta: int, admin_ids: Sequence[int]) -> None:
    parsed = _parse_size_cb(c.data)
    if parsed is None:
        await c.answer()
        return
    product_id, size = parsed
    text, log_id = await apply_change(c.bot, c.from_user, product_id, size, delta, admin_ids)
    if log_id is None:  # ошибка: показываем и обновляем экран
        await c.answer(text.replace("<b>", "").replace("</b>", "")[:190], show_alert=True)
        await render_sizes(c, product_id, "sell" if delta < 0 else "add")
        return
    await c.answer("Готово")
    await render_sizes(c, product_id, "sell" if delta < 0 else "add", note=text, undo_id=log_id)


@router.callback_query(F.data.startswith("a:sd:"))
async def cb_tap_sell(c: CallbackQuery, admin_ids: Sequence[int] = ()):
    await _tap(c, -1, admin_ids)


@router.callback_query(F.data.startswith("a:sa:"))
async def cb_tap_add(c: CallbackQuery, admin_ids: Sequence[int] = ()):
    await _tap(c, +1, admin_ids)


# ---------- отмена ----------

_UNDO_FAIL = {
    "not_found": "Запись не найдена.",
    "already": "Эта операция уже отменена.",
    "missing": "Не отменить: такого размера у товара уже нет.",
    "conflict": "Не отменить: после этого остаток ушёл бы в минус (его уже успели продать).",
}


async def _undo(log_id: int):
    status, qty, product_id, size, delta = db.undo_log(log_id)
    if status != "ok":
        return _UNDO_FAIL[status], product_id, False
    name = (db.get_product_details(product_id) or (None, "товар"))[1]
    return f"↩️ Отменено: <b>{esc(name)}</b> · {esc(size)}, снова <b>{qty}</b> шт.", product_id, True


@router.callback_query(F.data.startswith("a:un:"))
async def cb_undo(c: CallbackQuery):
    args = parse_args(c.data, "a:un", 1)
    if not args:
        await c.answer()
        return
    text, _pid, ok = await _undo(args[0])
    await c.answer("Отменено" if ok else text[:190], show_alert=not ok)
    if ok:
        await show_text(c, text, None)


@router.callback_query(F.data.startswith("a:unp:"))
async def cb_undo_on_screen(c: CallbackQuery):
    args = parse_args(c.data, "a:unp", 1)
    if not args:
        await c.answer()
        return
    text, product_id, ok = await _undo(args[0])
    await c.answer("Отменено" if ok else text[:190], show_alert=not ok)
    if product_id is not None:
        await render_sizes(c, product_id, "sell", note=text if ok else "")


@router.callback_query(F.data == "a:unl")
async def cb_undo_last(c: CallbackQuery):
    log_id = db.last_log_id(c.from_user.id)
    if log_id is None:
        await c.answer("Нечего отменять", show_alert=True)
        return
    text, _pid, ok = await _undo(log_id)
    await c.answer("Отменено" if ok else text[:190], show_alert=not ok)
    if ok:
        await show_text(c, text + "\n\n" + home_text(), ui.stock_menu_kb())


# ---------- журнал ----------

@router.callback_query(F.data == "a:st_log")
async def cb_log(c: CallbackQuery, tz_offset: int = 3):
    rows = db.recent_log(15)
    if not rows:
        text = "Журнал пуст."
    else:
        lines = ["<b>Последние операции</b>", ""]
        for _id, ts, who, pid, name, size, delta, qty_after, note, undone in rows:
            what = "размеры" if note == "set" else _minus(delta)
            line = (f"{format_ts(ts, tz_offset)} · {esc(who)} · №{pid} {esc(truncate(name, 20))} "
                    f"{esc(size)} {what} → {qty_after}")
            lines.append(f"<s>{line}</s> (отменено)" if undone else line)
        text = "\n".join(lines)
    await show_text(c, text, ui.back_to_stock_kb())
    await c.answer()


# ---------- задать размеры ----------

SET_HELP = (
    "Пришлите размеры и количество через пробел:\n"
    "<code>S2 M3 L1 XL0</code> — буквенные размеры\n"
    "<code>42:2 43:1</code> — числовые (через двоеточие)\n"
    "«<code>-</code>» — не вести учёт размеров у этого товара.\n"
    "Новый список <b>полностью заменит</b> текущий. Отмена — /cancel"
)


@router.callback_query(F.data == "a:st_set")
async def cb_set_start(c: CallbackQuery):
    cats = db.get_categories()
    if not cats:
        await c.answer("Категорий нет!", show_alert=True)
        return
    await show_text(c, "✏️ Выберите категорию:", ui.admin_cats_kb(cats, "a:ssc", back="a:stock"))
    await c.answer()


@router.callback_query(F.data.startswith("a:ssc:"))
async def cb_set_category(c: CallbackQuery):
    args = parse_args(c.data, "a:ssc", 1)
    name = db.get_category(args[0]) if args else None
    products = db.get_products_by_category(args[0]) if name else []
    if not products:
        await c.answer("В категории нет товаров", show_alert=True)
        return
    await show_text(c, f"<b>{esc(name)}</b>\nУ какого товара задать размеры?",
                    ui.stock_products_kb(products, "a:ssp", back="a:st_set"))
    await c.answer()


@router.callback_query(F.data.startswith("a:ssp:"))
async def cb_set_product(c: CallbackQuery, state: FSMContext):
    args = parse_args(c.data, "a:ssp", 1)
    details = db.get_product_details(args[0]) if args else None
    if details is None:
        await c.answer("Товар не найден", show_alert=True)
        return
    await state.set_state(StockStates.setting)
    await state.update_data(product_id=args[0])
    msg = msg_of(c)
    if msg:
        await msg.answer(
            f"<b>{esc(details[1])}</b> · №{args[0]}\nСейчас: {stock_line(db.get_stock(args[0]))}\n\n{SET_HELP}"
        )
    await c.answer()


# Команды (/cancel, /start...) не перехватываем — их обработают другие роутеры.
@router.message(StockStates.setting, F.text, ~F.text.startswith("/"))
async def msg_set_sizes(m: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data.get("product_id")
    details = db.get_product_details(product_id) if product_id else None
    if details is None:
        await state.clear()
        await m.answer("Товар уже удалён. Начните заново.", reply_markup=ui.stock_menu_kb())
        return
    raw = m.text.strip()
    try:
        sizes = [] if raw in ("-", "—") else parse_sizes(raw)
    except ValueError as e:
        await m.answer(f"⚠️ {esc(str(e))}")
        return
    db.touch_admin(m.from_user.id, m.from_user.first_name or m.from_user.username or str(m.from_user.id))
    db.set_stock(product_id, sizes, m.from_user.id)
    await state.clear()
    await m.answer(
        f"✅ <b>{esc(details[1])}</b> · №{product_id}\n{stock_line(db.get_stock(product_id))}",
        reply_markup=ui.stock_menu_kb(),
    )


@router.message(StockStates.setting, ~F.text)
async def msg_set_sizes_not_text(m: Message):
    await m.answer("✏️ Нужен обычный текст, например: S2 M3 L1. Или /cancel.")
