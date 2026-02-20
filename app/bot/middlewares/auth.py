from __future__ import annotations

from collections.abc import Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


def is_user_allowed(user_id: int, allowed_ids: set[int]) -> bool:
    return user_id in allowed_ids


class AuthMiddleware(BaseMiddleware):
    def __init__(self, allowed_ids: set[int]) -> None:
        self.allowed_ids = allowed_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict], Awaitable[object]],
        event: TelegramObject,
        data: dict,
    ) -> object:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        if is_user_allowed(user.id, self.allowed_ids):
            return await handler(event, data)

        if isinstance(event, Message):
            await event.answer("⛔ Доступ запрещен. Ваш Telegram ID не в whitelist.")
        elif isinstance(event, CallbackQuery):
            await event.answer("Доступ запрещен", show_alert=True)

        return None
