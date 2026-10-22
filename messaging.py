"""Общие помощники для отправки/редактирования сообщений."""
import logging
from typing import Optional

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

log = logging.getLogger(__name__)


def msg_of(c: CallbackQuery) -> Optional[Message]:
    """Сообщение под кнопкой или None, если оно недоступно (слишком старое)."""
    msg = c.message
    return msg if isinstance(msg, Message) else None


async def show_text(c: CallbackQuery, text: str, kb: Optional[InlineKeyboardMarkup] = None) -> None:
    """Показывает текст на месте текущего сообщения.
    Если там фото (его нельзя превратить в текст) — удаляет и отправляет новое."""
    msg = msg_of(c)
    if msg is None:
        return
    if msg.photo:
        try:
            await msg.delete()
        except TelegramBadRequest:
            pass
        await msg.answer(text, reply_markup=kb)
        return
    try:
        await msg.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            log.warning("edit_text failed: %s", e)
            await msg.answer(text, reply_markup=kb)
