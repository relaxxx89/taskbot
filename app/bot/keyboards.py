from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.db.models import BoardColumn


def main_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Новая"), KeyboardButton(text="📋 Доска")],
            [KeyboardButton(text="📅 Сегодня"), KeyboardButton(text="🚨 Просрочено")],
            [KeyboardButton(text="📦 Экспорт"), KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите действие",
    )


def board_controls_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Новая", callback_data="task:create")
    kb.button(text="Сегодня", callback_data="filter:set:today")
    kb.button(text="Просрочено", callback_data="filter:set:overdue")
    kb.button(text="Все", callback_data="filter:set:all")
    kb.button(text="Экспорт", callback_data="export:run")
    kb.adjust(1, 3, 1)
    return kb.as_markup()


def new_task_due_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Сегодня 18:00", callback_data="task:due:today18")
    kb.button(text="Завтра 10:00", callback_data="task:due:tomorrow10")
    kb.button(text="+3 дня", callback_data="task:due:plus3d")
    kb.button(text="Без срока", callback_data="task:due:none")
    kb.button(text="Ввести вручную", callback_data="task:due:custom")
    kb.button(text="Отмена", callback_data="task:new:cancel")
    kb.adjust(2, 2, 1, 1)
    return kb.as_markup()


def new_task_nav_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Пропустить", callback_data="task:new:skip")
    kb.button(text="Отмена", callback_data="task:new:cancel")
    kb.adjust(2)
    return kb.as_markup()


def post_create_edit_keyboard(task_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🏷 Теги", callback_data=f"task:edit:tags:{task_id}")
    kb.button(text="⚡ Приоритет", callback_data=f"task:edit:priority:{task_id}")
    kb.button(text="📝 Описание", callback_data=f"task:edit:description:{task_id}")
    kb.button(text="✅ Done", callback_data=f"task:done:{task_id}")
    kb.button(text="↔ Move", callback_data=f"task:move:{task_id}")
    kb.button(text="⏭ +1 день", callback_data=f"task:postpone:{task_id}")
    kb.adjust(3, 3)
    return kb.as_markup()


def task_actions_keyboard(task_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Done", callback_data=f"task:done:{task_id}")
    kb.button(text="↔ Move", callback_data=f"task:move:{task_id}")
    kb.button(text="⏭ +1 день", callback_data=f"task:postpone:{task_id}")
    kb.adjust(3)
    return kb.as_markup()


def task_priority_keyboard(task_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="P1", callback_data=f"task:priority:set:{task_id}:1")
    kb.button(text="P2", callback_data=f"task:priority:set:{task_id}:2")
    kb.button(text="P3", callback_data=f"task:priority:set:{task_id}:3")
    kb.adjust(3)
    return kb.as_markup()


def move_task_keyboard(task_id: int, columns: list[BoardColumn]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for column in columns:
        kb.button(text=column.name, callback_data=f"column:switch:{task_id}:{column.id}")
    kb.adjust(2)
    return kb.as_markup()


def timezone_settings_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🌍 Таймзона", callback_data="settings:timezone")
    kb.adjust(1)
    return kb.as_markup()


def timezone_quick_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Europe/Moscow", callback_data="settings:timezone:set:Europe/Moscow")
    kb.button(text="Europe/Samara", callback_data="settings:timezone:set:Europe/Samara")
    kb.button(text="UTC", callback_data="settings:timezone:set:UTC")
    kb.button(text="Ввести вручную", callback_data="settings:timezone:custom")
    kb.button(text="Назад", callback_data="settings:timezone:back")
    kb.adjust(1, 1, 1, 1, 1)
    return kb.as_markup()
