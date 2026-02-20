from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Callable
from zoneinfo import ZoneInfo

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Board, NotificationLog, Task, User
from app.services.task_service import list_overdue_tasks, list_today_tasks
from app.utils.datetime_utils import format_dt

logger = logging.getLogger(__name__)


async def _notification_sent(session: AsyncSession, dedupe_key: str) -> bool:
    result = await session.execute(select(NotificationLog.id).where(NotificationLog.dedupe_key == dedupe_key))
    return result.scalar_one_or_none() is not None


async def _log_notification(
    session: AsyncSession,
    *,
    user_id: int | None,
    task_id: int | None,
    event_type: str,
    dedupe_key: str,
    delivery_status: str,
) -> None:
    session.add(
        NotificationLog(
            user_id=user_id,
            task_id=task_id,
            type=event_type,
            dedupe_key=dedupe_key,
            delivery_status=delivery_status,
        )
    )
    await session.flush()


async def process_reminders(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
    now_utc: datetime | None = None,
) -> None:
    now = now_utc or datetime.now(UTC)
    async with session_factory() as session:
        result = await session.execute(
            select(Task, User)
            .join(Board, Board.id == Task.board_id)
            .join(User, User.id == Board.owner_id)
            .where(
                Task.completed_at.is_(None),
                Task.reminder_at.is_not(None),
                Task.reminder_at <= now,
            )
            .order_by(Task.reminder_at.asc())
        )
        rows = result.all()

        for task, user in rows:
            if task.reminder_at is None:
                continue
            dedupe_key = f"reminder:{task.id}:{task.reminder_at.isoformat()}"
            if await _notification_sent(session, dedupe_key):
                continue

            text = (
                "⏰ Напоминание\n"
                f"Задача #{task.id}: {task.title}\n"
                f"Срок: {format_dt(task.due_at, user.timezone)}"
            )
            try:
                await bot.send_message(user.telegram_id, text)
                await _log_notification(
                    session,
                    user_id=user.id,
                    task_id=task.id,
                    event_type="reminder",
                    dedupe_key=dedupe_key,
                    delivery_status="sent",
                )
            except Exception:
                logger.exception("Failed to send reminder", extra={"task_id": task.id, "user_id": user.id})
                await _log_notification(
                    session,
                    user_id=user.id,
                    task_id=task.id,
                    event_type="reminder",
                    dedupe_key=f"{dedupe_key}:failed:{int(now.timestamp())}",
                    delivery_status="failed",
                )

        await session.commit()


async def process_digest(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
    *,
    digest_hour: int,
    digest_minute: int,
    now_utc: datetime | None = None,
) -> None:
    now = now_utc or datetime.now(UTC)
    async with session_factory() as session:
        users_result = await session.execute(select(User).where(User.digest_enabled.is_(True)))
        users = list(users_result.scalars().all())

        for user in users:
            user_now = now.astimezone(ZoneInfo(user.timezone))
            if user_now.hour != digest_hour or user_now.minute != digest_minute:
                continue

            dedupe_key = f"digest:{user.id}:{user_now.date().isoformat()}"
            if await _notification_sent(session, dedupe_key):
                continue

            board_result = await session.execute(select(Board).where(Board.owner_id == user.id))
            board = board_result.scalar_one_or_none()
            if board is None:
                continue

            today_tasks = await list_today_tasks(session, board.id, user.timezone)
            overdue_tasks = await list_overdue_tasks(session, board.id, user.timezone)

            lines = ["🗓 Ежедневный дайджест", ""]
            if overdue_tasks:
                lines.append(f"Просрочено: {len(overdue_tasks)}")
            else:
                lines.append("Просроченных нет")
            if today_tasks:
                lines.append(f"На сегодня: {len(today_tasks)}")
            else:
                lines.append("На сегодня задач нет")

            lines.append("")
            for task in overdue_tasks[:5]:
                lines.append(f"• [OVERDUE] #{task.id} {task.title}")
            for task in today_tasks[:5]:
                lines.append(f"• [TODAY] #{task.id} {task.title}")

            text = "\n".join(lines)
            try:
                await bot.send_message(user.telegram_id, text)
                await _log_notification(
                    session,
                    user_id=user.id,
                    task_id=None,
                    event_type="digest",
                    dedupe_key=dedupe_key,
                    delivery_status="sent",
                )
            except Exception:
                logger.exception("Failed to send digest", extra={"user_id": user.id})
                await _log_notification(
                    session,
                    user_id=user.id,
                    task_id=None,
                    event_type="digest",
                    dedupe_key=f"{dedupe_key}:failed:{int(now.timestamp())}",
                    delivery_status="failed",
                )

        await session.commit()


def build_scheduler_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
    digest_hour: int,
    digest_minute: int,
) -> dict[str, Callable[[], object]]:
    return {
        "reminders": lambda: process_reminders(session_factory, bot),
        "digest": lambda: process_digest(
            session_factory,
            bot,
            digest_hour=digest_hour,
            digest_minute=digest_minute,
        ),
    }
