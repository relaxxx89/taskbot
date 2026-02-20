from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.task_service import create_task, list_overdue_tasks, list_today_tasks, mark_task_done, move_task
from app.services.user_board_service import bootstrap_user_board, list_columns


@pytest.mark.asyncio
async def test_create_move_done_today_overdue(session_factory) -> None:
    async with session_factory() as session:
        user, board, columns = await bootstrap_user_board(session, telegram_id=42, tz_default="Europe/Moscow")
        doing_col = columns[2]

        now_local = datetime.now(ZoneInfo("Europe/Moscow"))
        today_due = now_local.replace(hour=20, minute=0, second=0, microsecond=0).astimezone(UTC)
        overdue_due = (now_local - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0).astimezone(UTC)

        task_today = await create_task(
            session,
            board_id=board.id,
            title="Today task",
            description="",
            priority=2,
            due_at=today_due,
            tag_names=["work"],
        )
        await create_task(
            session,
            board_id=board.id,
            title="Old task",
            description="",
            priority=2,
            due_at=overdue_due,
            tag_names=[],
        )
        moving_task = await create_task(
            session,
            board_id=board.id,
            title="Move me",
            description="",
            priority=1,
            due_at=None,
            tag_names=[],
        )

        await move_task(session, board.id, moving_task.id, doing_col)
        done_task = await mark_task_done(session, board.id, moving_task.id)

        await session.commit()

        today = await list_today_tasks(session, board.id, user.timezone)
        overdue = await list_overdue_tasks(session, board.id, user.timezone)

        assert task_today.id in {task.id for task in today}
        assert any(task.title == "Old task" for task in overdue)
        assert done_task.status == "done"
        assert done_task.completed_at is not None

        cols = await list_columns(session, board.id)
        assert len(cols) == 4
