from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models import BoardColumn


def board_controls_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Новая", callback_data="task:create")
    kb.button(text="Сегодня", callback_data="filter:set:today")
    kb.button(text="Просрочено", callback_data="filter:set:overdue")
    kb.button(text="Все", callback_data="filter:set:all")
    kb.button(text="Экспорт", callback_data="export:run")
    kb.adjust(1, 3, 1)
    return kb.as_markup()


def task_actions_keyboard(task_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Done", callback_data=f"task:done:{task_id}")
    kb.button(text="↔ Move", callback_data=f"task:move:{task_id}")
    kb.button(text="⏭ +1 день", callback_data=f"task:postpone:{task_id}")
    kb.adjust(3)
    return kb.as_markup()


def move_task_keyboard(task_id: int, columns: list[BoardColumn]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for column in columns:
        kb.button(text=column.name, callback_data=f"column:switch:{task_id}:{column.id}")
    kb.adjust(2)
    return kb.as_markup()
