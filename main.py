import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeChat, ErrorEvent

import database as db
from admin_handlers import router as admin_router
from config import load_config
from stock_handlers import router as stock_router
from user_handlers import router as user_router
from utils import truncate

log = logging.getLogger("outfit")

USER_COMMANDS = [
    BotCommand(command="start", description="Начать"),
    BotCommand(command="catalog", description="Каталог"),
    BotCommand(command="look", description="Мой образ"),
    BotCommand(command="about", description="О бренде"),
]

DEFAULT_BANNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "banner.png")


async def on_error(event: ErrorEvent) -> bool:
    log.exception("Необработанная ошибка: %s", event.exception)
    callback = event.update.callback_query
    if callback:
        try:
            await callback.answer("Что-то пошло не так. Попробуйте ещё раз.", show_alert=True)
        except Exception:
            pass
    return True


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()

    db.init_db()

    session = AiohttpSession(proxy=cfg.proxy) if cfg.proxy else None
    bot = Bot(token=cfg.token, session=session,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    welcome_photo = cfg.welcome_photo or (DEFAULT_BANNER if os.path.isfile(DEFAULT_BANNER) else None)
    dp = Dispatcher(welcome_photo=welcome_photo, brand=cfg.brand,
                    admin_ids=cfg.admin_ids, tz_offset=cfg.tz_offset,
                    catalog_mode=cfg.catalog_mode)

    # Админская часть доступна всем админам из ADMIN_ID (их может быть несколько).
    for admin_only in (admin_router, stock_router):
        admin_only.message.filter(F.from_user.id.in_(cfg.admin_ids))
        admin_only.callback_query.filter(F.from_user.id.in_(cfg.admin_ids))

    # Порядок важен. Остатки — первыми: иначе клиентская «заглушка» перехватит сообщения вида «12 M».
    # Потом клиентские команды и кнопки (они сбрасывают диалог админки), и только потом админка.
    dp.include_router(stock_router)
    dp.include_router(user_router)
    dp.include_router(admin_router)
    dp.errors.register(on_error)

    await bot.set_my_commands(USER_COMMANDS)
    for admin_id in cfg.admin_ids:
        try:
            await bot.set_my_commands(
                USER_COMMANDS + [BotCommand(command="admin", description="Панель админа")],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception as e:  # админ мог ещё ни разу не написать боту
            log.warning("Не удалось назначить меню команд админу %s: %s", admin_id, e)

    # Описание бота в профиле (то, что видно до нажатия «Старт») — из настроек бренда.
    try:
        await bot.set_my_short_description(short_description=truncate(cfg.brand.tagline, 120))
        await bot.set_my_description(description=truncate(
            f"{cfg.brand.name} — {cfg.brand.tagline}.\n\n"
            "Коллекция, подборка образа из понравившихся вещей и новинки — всё в одном чате.", 512))
    except Exception as e:
        log.warning("Не удалось обновить описание бота: %s", e)

    me = await bot.get_me()
    log.info("Бот @%s запущен", me.username)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
