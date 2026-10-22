"""Настройки бота из переменных окружения / .env."""
import os
import re
from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple

DEFAULT_TAGLINE = "Персональный бутик стиля"
DEFAULT_ABOUT = (
    "Мы собираем коллекции, в которых легко чувствовать себя собой.\n"
    "Листайте каталог и складывайте понравившиеся вещи в «Мой образ»."
)


@dataclass(frozen=True)
class Brand:
    """Всё, что клиент видит как «лицо» магазина. Меняется в .env — код трогать не нужно."""
    name: str = "Outfit"
    tagline: str = DEFAULT_TAGLINE
    about: str = DEFAULT_ABOUT
    contact_url: Optional[str] = None  # ссылка для кнопки «Написать нам» (необязательно)


@dataclass(frozen=True)
class Config:
    token: str
    admin_ids: Tuple[int, ...]  # все админы равноправны: каталог, остатки, рассылки
    proxy: Optional[str] = None
    welcome_photo: Optional[str] = None
    brand: Brand = field(default_factory=Brand)
    tz_offset: int = 3  # часовой пояс магазина (часы от UTC) — для времени в журнале остатков
    catalog_mode: str = "carousel"  # carousel — одна карточка, листание ‹ ›; feed — все вещи ленты сообщений

    @property
    def admin_id(self) -> int:
        return self.admin_ids[0]


def normalize_contact(value: str) -> Optional[str]:
    """'@shop' -> 'https://t.me/shop'; http(s)/tg-ссылки без изменений; остальное — игнорируем."""
    value = (value or "").strip()
    if not value:
        return None
    if value.startswith("@") and len(value) > 1:
        return f"https://t.me/{value[1:]}"
    if value.startswith(("https://", "http://", "tg://")):
        return value
    return None


def parse_admin_ids(raw: str) -> Tuple[int, ...]:
    """'111, 222;333' -> (111, 222, 333). Пусто или мусор — пустой кортеж."""
    tokens = [t for t in re.split(r"[,\s;]+", (raw or "").strip()) if t]
    if not tokens or not all(t.isascii() and t.isdigit() for t in tokens):
        return ()
    return tuple(dict.fromkeys(int(t) for t in tokens))  # без дублей, порядок сохраняем


def load_config(env: Optional[Mapping[str, str]] = None) -> Config:
    """Читает настройки. Без env берёт .env и окружение; с env — только его (для тестов)."""
    if env is None:
        from dotenv import load_dotenv

        load_dotenv()
        env = os.environ

    token = (env.get("BOT_TOKEN") or "").strip()
    raw_admin = (env.get("ADMIN_ID") or "").strip()

    if not token:
        raise SystemExit("Не задан BOT_TOKEN. Скопируйте .env.example в .env и впишите токен от BotFather.")
    admin_ids = parse_admin_ids(raw_admin)
    if not admin_ids:
        raise SystemExit(
            "ADMIN_ID должен быть числом или списком чисел через запятую, например 111111,222222 "
            "(Telegram ID, его показывает @userinfobot)."
        )
    raw_tz = (env.get("TZ_OFFSET") or "3").strip()
    try:
        tz_offset = int(raw_tz)
    except ValueError:
        raise SystemExit("TZ_OFFSET должен быть целым числом часов от UTC, например 3 для Москвы.")
    if not -12 <= tz_offset <= 14:
        raise SystemExit("TZ_OFFSET должен быть от -12 до 14.")

    catalog_mode = (env.get("CATALOG_MODE") or "carousel").strip().lower()
    if catalog_mode not in ("carousel", "feed"):
        raise SystemExit("CATALOG_MODE должен быть carousel (по одной карточке) или feed (лентой сообщений).")

    brand = Brand(
        name=(env.get("BRAND_NAME") or "").strip() or Brand.name,
        tagline=(env.get("BRAND_TAGLINE") or "").strip() or DEFAULT_TAGLINE,
        about=(env.get("BRAND_ABOUT") or "").replace("\\n", "\n").strip() or DEFAULT_ABOUT,
        contact_url=normalize_contact(env.get("CONTACT_URL", "")),
    )
    return Config(
        token=token,
        admin_ids=admin_ids,
        proxy=(env.get("PROXY_URL") or "").strip() or None,
        welcome_photo=(env.get("WELCOME_PHOTO") or "").strip() or None,
        brand=brand,
        tz_offset=tz_offset,
        catalog_mode=catalog_mode,
    )
