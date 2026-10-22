import asyncio
import logging
import os
import sqlite3
from typing import Optional

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, InputMediaPhoto, Message

import database as db
import ui
from config import Brand
from messaging import msg_of, show_text
from utils import MAX_LOOK_ITEMS, clamp, esc, look_text, parse_args, plural, product_caption

log = logging.getLogger(__name__)
router = Router(name="user")

DEFAULT_BRAND = Brand()
FEED_PAGE = 10  # сколько вещей за раз показывать в режиме ленты (дальше — «Показать ещё»)
_photo_cache = {}  # путь к локальному баннеру -> file_id (чтобы не загружать файл при каждом /start)

HELP = (
    "<b>Как это работает</b>\n\n"
    "<b>Каталог</b> — выберите категорию и листайте вещи кнопками ‹ ›.\n"
    f"<b>Мой образ</b> — подборка понравившегося с общей суммой. Вмещает до {MAX_LOOK_ITEMS} вещей.\n\n"
    "<i>/catalog · /look · /about</i>"
)
CATALOG_TITLE = "<b>Каталог</b>\nВыберите категорию"
CATALOG_EMPTY = "Коллекция скоро появится — загляните чуть позже."
LOOK_EMPTY = "<b>Мой образ</b>\n\nПока пусто. Загляните в каталог и добавьте то, что понравится."


def welcome_text(brand: Brand, first_name: Optional[str]) -> str:
    greet = f"Добро пожаловать, {esc(first_name)}." if first_name else "Добро пожаловать."
    return (
        f"<b>{esc(brand.name.upper())}</b>\n"
        f"<i>{esc(brand.tagline)}</i>\n\n"
        f"{greet} Листайте коллекцию и собирайте образ из понравившихся вещей — всё в одном месте."
    )


def about_text(brand: Brand) -> str:
    return (
        f"<b>{esc(brand.name.upper())}</b>\n"
        f"<i>{esc(brand.tagline)}</i>\n\n"
        f"{esc(brand.about)}"
    )


def build_catalog(user_id: int):
    cats = db.get_categories()
    if not cats:
        return CATALOG_EMPTY, None
    return CATALOG_TITLE, ui.catalog_kb(cats, db.cart_count(user_id))


def build_look(user_id: int):
    items = db.get_cart_items(user_id)
    if not items:
        return LOOK_EMPTY, ui.to_catalog_kb()
    return look_text(items), ui.look_kb(items)


async def send_banner(m: Message, source: str, caption: str, kb) -> None:
    """Баннер: локальный файл (грузим один раз, дальше берём file_id), file_id или ссылка."""
    if source in _photo_cache:
        photo = _photo_cache[source]
    elif os.path.isfile(source):
        photo = FSInputFile(source)
    else:
        photo = source
    sent = await m.answer_photo(photo, caption=caption, reply_markup=kb)
    if isinstance(photo, FSInputFile) and sent is not None and getattr(sent, "photo", None):
        _photo_cache[source] = sent.photo[-1].file_id


# ---------- команды и кнопки меню ----------

@router.message(Command("start"))
async def cmd_start(m: Message, state: FSMContext, brand: Brand = DEFAULT_BRAND,
                    welcome_photo: Optional[str] = None):
    await state.clear()
    await cleanup_feed(m.bot, m.chat.id)
    if m.from_user is None:
        return
    db.register_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    text = welcome_text(brand, m.from_user.first_name)

    sent = False
    if welcome_photo:
        try:
            await send_banner(m, welcome_photo, text, ui.main_reply_kb())
            sent = True
        except TelegramBadRequest as e:
            log.warning("Баннер не отправился (%s) — показываю текстом", e)
    if not sent:
        await m.answer(text, reply_markup=ui.main_reply_kb())

    text, kb = build_catalog(m.from_user.id)
    await m.answer(text, reply_markup=kb)


@router.message(Command("help"))
async def cmd_help(m: Message, state: FSMContext):
    await state.clear()
    await cleanup_feed(m.bot, m.chat.id)
    await m.answer(HELP)


@router.message(Command("about"))
@router.message(F.text == ui.BTN_ABOUT)
async def cmd_about(m: Message, state: FSMContext, brand: Brand = DEFAULT_BRAND):
    await state.clear()
    await cleanup_feed(m.bot, m.chat.id)
    await m.answer(about_text(brand), reply_markup=ui.about_kb(brand.contact_url))


@router.message(Command("catalog"))
@router.message(F.text == ui.BTN_CATALOG)
async def cmd_catalog(m: Message, state: FSMContext):
    await state.clear()
    await cleanup_feed(m.bot, m.chat.id)
    if m.from_user is None:
        return
    text, kb = build_catalog(m.from_user.id)
    await m.answer(text, reply_markup=kb)


@router.message(Command("look"))
@router.message(F.text == ui.BTN_LOOK)
async def cmd_look(m: Message, state: FSMContext):
    await state.clear()
    await cleanup_feed(m.bot, m.chat.id)
    if m.from_user is None:
        return
    text, kb = build_look(m.from_user.id)
    await m.answer(text, reply_markup=kb)


# ---------- режим «лента»: вещи сообщениями подряд, «Назад» их удаляет ----------

async def cleanup_feed(bot, chat_id: int, keep=None) -> None:
    """Удаляет из чата все сообщения открытой ленты (кроме keep). Ошибки Telegram не страшны:
    сообщения старше 48 часов он удалить не даёт — они просто останутся."""
    ids = [i for i in db.feed_pop(chat_id) if i != keep]
    for start in range(0, len(ids), 100):
        try:
            await bot.delete_messages(chat_id=chat_id, message_ids=ids[start:start + 100])
        except TelegramAPIError as e:
            log.info("Не удалось удалить сообщения ленты: %s", e)


async def _call(func, **kwargs):
    """Вызов Telegram с одним повтором, если он попросил подождать."""
    for _ in range(2):
        try:
            return await func(**kwargs)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
    return None


async def _send_feed_card(bot, chat_id: int, user_id: int, category_name: str, product_id: int):
    details = db.get_product_details(product_id)
    if details is None:
        return None
    _cid, name, description, price, photo_id = details
    caption = product_caption(name, description, price, category_name,
                              sizes=db.get_stock(product_id), product_id=product_id)
    kb = ui.feed_card_kb(product_id, db.is_in_cart(user_id, product_id))
    sent = None
    if photo_id:
        try:
            sent = await _call(bot.send_photo, chat_id=chat_id, photo=photo_id, caption=caption, reply_markup=kb)
        except TelegramBadRequest as e:
            log.warning("Фото товара %s не отправилось: %s", product_id, e)
    if sent is None:
        sent = await _call(bot.send_message, chat_id=chat_id, text=caption, reply_markup=kb)
    return sent.message_id if sent is not None else None


async def send_feed_page(bot, chat_id: int, user_id: int, category_id: int, offset: int):
    """Отправляет очередную порцию вещей и итоговое сообщение с кнопками. Возвращает id сообщений."""
    category_name = db.get_category(category_id)
    products = db.get_products_by_category(category_id)
    page = products[offset:offset + FEED_PAGE]
    ids = []
    for product_id, _name in page:
        mid = await _send_feed_card(bot, chat_id, user_id, category_name or "", product_id)
        if mid:
            ids.append(mid)
        await asyncio.sleep(0.1)  # не упираемся в лимит Telegram на частоту сообщений
    shown = min(offset + FEED_PAGE, len(products))
    tail = "<i>Это всё в этой категории</i>" if shown >= len(products) else f"<i>Показано {shown} из {len(products)}</i>"
    end = await _call(bot.send_message, chat_id=chat_id, text=tail,
                      reply_markup=ui.feed_end_kb(category_id, shown, len(products)))
    if end is not None:
        ids.append(end.message_id)
    db.feed_add(chat_id, ids)
    return ids


async def open_feed(c: CallbackQuery, category_id: int) -> None:
    msg = msg_of(c)
    if msg is None:
        return
    category_name = db.get_category(category_id)
    if category_name is None:
        text, kb = build_catalog(c.from_user.id)
        await show_text(c, text, kb)
        return
    products = db.get_products_by_category(category_id)
    if not products:
        await show_text(c, f"В категории <b>{esc(category_name)}</b> пока ничего нет.", ui.to_catalog_kb())
        return

    await cleanup_feed(c.bot, msg.chat.id, keep=msg.message_id)  # предыдущая лента, если осталась
    n = len(products)
    header = f"<b>{esc(category_name)}</b>\n<i>{n} {plural(n, ('вещь', 'вещи', 'вещей'))}</i>"
    # Сообщение со списком категорий превращается в заголовок ленты и удаляется вместе с ней.
    if msg.photo:
        await msg.delete()
        sent = await _call(c.bot.send_message, chat_id=msg.chat.id, text=header)
        header_id = sent.message_id if sent else None
    else:
        try:
            await msg.edit_text(header)
        except TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise
        header_id = msg.message_id
    if header_id:
        db.feed_add(msg.chat.id, [header_id])
    await send_feed_page(c.bot, msg.chat.id, c.from_user.id, category_id, 0)


@router.callback_query(F.data.startswith("more:"))
async def cb_feed_more(c: CallbackQuery):
    args = parse_args(c.data, "more", 2)
    msg = msg_of(c)
    await c.answer()
    if not args or msg is None or db.get_category(args[0]) is None:
        return
    try:
        await msg.delete()  # старое итоговое сообщение заменится новым
    except TelegramBadRequest:
        pass
    await send_feed_page(c.bot, msg.chat.id, c.from_user.id, args[0], args[1])


@router.callback_query(F.data == "fb")
async def cb_feed_back(c: CallbackQuery):
    """«Назад» в ленте: убираем из чата все вещи и показываем список категорий заново."""
    msg = msg_of(c)
    await c.answer()
    if msg is None:
        return
    await cleanup_feed(c.bot, msg.chat.id)
    try:
        await msg.delete()  # на случай, если лента была потеряна (перезапуск бота, давность)
    except TelegramAPIError:
        pass
    text, kb = build_catalog(c.from_user.id)
    await c.bot.send_message(chat_id=msg.chat.id, text=text, reply_markup=kb)


@router.callback_query(F.data.startswith("tf:"))
async def cb_feed_toggle(c: CallbackQuery):
    args = parse_args(c.data, "tf", 1)
    msg = msg_of(c)
    if not args or msg is None:
        await c.answer()
        return
    product_id, uid = args[0], c.from_user.id
    if db.get_product_details(product_id) is None:
        await c.answer("Эта вещь больше недоступна", show_alert=True)
        return
    if db.is_in_cart(uid, product_id):
        db.remove_from_cart(uid, product_id)
        toast = "Убрано из образа"
    elif db.cart_count(uid) >= MAX_LOOK_ITEMS:
        await c.answer(f"В образе уже {MAX_LOOK_ITEMS} вещей — это максимум", show_alert=True)
        return
    else:
        try:
            db.add_to_cart(uid, product_id)
        except sqlite3.IntegrityError:
            await c.answer("Эта вещь больше недоступна", show_alert=True)
            return
        toast = "Добавлено в образ"
    await c.answer(toast)
    try:
        await msg.edit_reply_markup(reply_markup=ui.feed_card_kb(product_id, db.is_in_cart(uid, product_id)))
    except TelegramBadRequest:
        pass


# ---------- каталог и карточки ----------

async def show_product(c: CallbackQuery, category_id: int, index: int) -> None:
    msg = msg_of(c)
    if msg is None:
        return

    category_name = db.get_category(category_id)
    if category_name is None:  # категорию удалили, пока клиент смотрел
        text, kb = build_catalog(c.from_user.id)
        await show_text(c, text, kb)
        return

    products = db.get_products_by_category(category_id)
    if not products:
        await show_text(c, f"В категории <b>{esc(category_name)}</b> пока ничего нет.", ui.to_catalog_kb())
        return

    index = clamp(index, len(products))
    product_id = products[index][0]
    details = db.get_product_details(product_id)
    if details is None:  # товар удалили между двумя запросами
        await show_text(c, "Эта вещь уже недоступна.", ui.to_catalog_kb())
        return

    _cid, name, description, price, photo_id = details
    caption = product_caption(name, description, price, category_name,
                              sizes=db.get_stock(product_id), product_id=product_id)
    kb = ui.product_kb(
        category_id, index, len(products), product_id,
        in_look=db.is_in_cart(c.from_user.id, product_id),
        look_count=db.cart_count(c.from_user.id),
    )

    # Листаем «на месте» — без удаления и повторной отправки (нет мерцания).
    if msg.photo and photo_id:
        try:
            await msg.edit_media(
                media=InputMediaPhoto(media=photo_id, caption=caption, parse_mode=ParseMode.HTML),
                reply_markup=kb,
            )
            return
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return
            log.info("edit_media не удалось (%s), отправляю заново", e)

    try:
        await msg.delete()
    except TelegramBadRequest:
        pass
    try:
        await msg.answer_photo(photo=photo_id, caption=caption, reply_markup=kb)
    except TelegramBadRequest as e:
        log.warning("Не удалось отправить фото товара %s: %s", product_id, e)
        await msg.answer(caption, reply_markup=kb)


@router.callback_query(F.data == "noop")
async def cb_noop(c: CallbackQuery):
    await c.answer()


@router.callback_query(F.data == "catalog")
async def cb_catalog(c: CallbackQuery):
    text, kb = build_catalog(c.from_user.id)
    await show_text(c, text, kb)
    await c.answer()


@router.callback_query(F.data.startswith("cat:"))
async def cb_category(c: CallbackQuery, catalog_mode: str = "carousel"):
    args = parse_args(c.data, "cat", 1)
    await c.answer()
    if not args:
        return
    if catalog_mode == "feed":
        await open_feed(c, args[0])
    else:
        await show_product(c, args[0], 0)


@router.callback_query(F.data.startswith("pg:"))
async def cb_page(c: CallbackQuery):
    args = parse_args(c.data, "pg", 2)
    await c.answer()
    if args:
        await show_product(c, args[0], args[1])


# ---------- образ ----------

@router.callback_query(F.data.startswith("tg:"))
async def cb_toggle(c: CallbackQuery):
    args = parse_args(c.data, "tg", 3)
    if not args:
        await c.answer()
        return
    product_id, category_id, index = args
    uid = c.from_user.id

    if db.get_product_details(product_id) is None:
        await c.answer("Эта вещь больше недоступна", show_alert=True)
        await show_product(c, category_id, index)
        return

    if db.is_in_cart(uid, product_id):
        db.remove_from_cart(uid, product_id)
        toast = "Убрано из образа"
    elif db.cart_count(uid) >= MAX_LOOK_ITEMS:
        await c.answer(f"В образе уже {MAX_LOOK_ITEMS} вещей — это максимум", show_alert=True)
        return
    else:
        try:
            db.add_to_cart(uid, product_id)
        except sqlite3.IntegrityError:  # товар удалили в этот самый момент
            await c.answer("Эта вещь больше недоступна", show_alert=True)
            await show_product(c, category_id, index)
            return
        toast = "Добавлено в образ"

    await c.answer(toast)
    msg = msg_of(c)
    if msg is None:
        return
    kb = ui.product_kb(
        category_id, index, len(db.get_products_by_category(category_id)), product_id,
        in_look=db.is_in_cart(uid, product_id), look_count=db.cart_count(uid),
    )
    try:
        await msg.edit_reply_markup(reply_markup=kb)
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "look")
async def cb_look(c: CallbackQuery):
    text, kb = build_look(c.from_user.id)
    msg = msg_of(c)
    if msg is not None and db.feed_ids(msg.chat.id):  # нажали из ленты: убираем её и показываем образ
        await cleanup_feed(c.bot, msg.chat.id)
        await c.bot.send_message(chat_id=msg.chat.id, text=text, reply_markup=kb)
    else:
        await show_text(c, text, kb)
    await c.answer()


@router.callback_query(F.data.startswith("rm:"))
async def cb_remove(c: CallbackQuery):
    args = parse_args(c.data, "rm", 1)
    if args:
        db.remove_from_cart(c.from_user.id, args[0])
    text, kb = build_look(c.from_user.id)
    await show_text(c, text, kb)
    await c.answer("Убрано")


@router.callback_query(F.data == "clr")
async def cb_clear(c: CallbackQuery):
    db.clear_cart(c.from_user.id)
    text, kb = build_look(c.from_user.id)
    await show_text(c, text, kb)
    await c.answer("Образ очищен")


# ---------- всё остальное (не команды, не в процессе диалога с админкой) ----------

@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def fallback(m: Message):
    await m.answer("Выберите раздел в меню внизу — так будет быстрее.",
                   reply_markup=ui.main_reply_kb())
