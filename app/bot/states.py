from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class NewTaskState(StatesGroup):
    title = State()
    description = State()
    due_at = State()
    priority = State()
    tags = State()
