from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.models import NotificationLog
from app.services.scheduler_service import process_reminders
from app.services.task_service import create_task
from app.services.user_board_service import bootstrap_user_board


@pytest.mark.asyncio
async def test_reminders_are_sent_once(session_factory, bot_stub) -> None:
    async with session_factory() as session:
        _, board, _, _ = await bootstrap_user_board(session, telegram_id=999, tz_default="UTC")
        due_at = datetime.now(UTC) + timedelta(minutes=30)
        task = await create_task(
            session,
            board_id=board.id,
            title="Reminder task",
            description="",
            priority=2,
            due_at=due_at,
            tag_names=[],
        )
        task.reminder_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()

    now = datetime.now(UTC)
    await process_reminders(session_factory, bot_stub, now_utc=now)
    await process_reminders(session_factory, bot_stub, now_utc=now)

    assert len(bot_stub.messages) == 1

    async with session_factory() as session:
        count = await session.scalar(
            select(func.count(NotificationLog.id)).where(
                NotificationLog.type == "reminder",
                NotificationLog.delivery_status == "sent",
                NotificationLog.task_id == task.id,
            )
        )
        assert count == 1
