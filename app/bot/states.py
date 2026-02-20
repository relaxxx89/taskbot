from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class NewTaskState(StatesGroup):
    title = State()
    due_choice = State()
    due_custom = State()


class EditTaskState(StatesGroup):
    tags = State()
    description = State()
    priority = State()
    timezone_custom = State()
