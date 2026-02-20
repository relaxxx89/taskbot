from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand


async def setup_bot_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="Запуск бота"),
        BotCommand(command="help", description="Справка"),
        BotCommand(command="new", description="Создать задачу"),
        BotCommand(command="board", description="Показать доску"),
        BotCommand(command="today", description="Задачи на сегодня"),
        BotCommand(command="overdue", description="Просроченные задачи"),
        BotCommand(command="move", description="Переместить задачу"),
        BotCommand(command="done", description="Завершить задачу"),
        BotCommand(command="edit", description="Переименовать задачу"),
        BotCommand(command="delete", description="Удалить задачу"),
        BotCommand(command="tags", description="Список тегов"),
        BotCommand(command="search", description="Поиск задач"),
        BotCommand(command="timezone", description="Сменить таймзону"),
        BotCommand(command="digest", description="Настройка дайджеста"),
        BotCommand(command="export", description="Экспорт в Markdown/CSV"),
        BotCommand(command="settings", description="Настройки колонок"),
    ]
    await bot.set_my_commands(commands)
