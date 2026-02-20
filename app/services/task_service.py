from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import BoardColumn, Tag, Task
from app.services.user_board_service import get_done_column, list_columns
from app.utils.datetime_utils import local_day_bounds_utc, next_reminder_at


async def _upsert_tags(session: AsyncSession, board_id: int, names: list[str]) -> list[Tag]:
    if not names:
        return []
    result = await session.execute(select(Tag).where(Tag.board_id == board_id, Tag.name.in_(names)))
    existing = {tag.name: tag for tag in result.scalars().all()}

    tags: list[Tag] = []
    for name in names:
        tag = existing.get(name)
        if tag is None:
            tag = Tag(board_id=board_id, name=name)
            session.add(tag)
            await session.flush()
            existing[name] = tag
        tags.append(tag)
    return tags


async def create_task(
    session: AsyncSession,
    *,
    board_id: int,
    title: str,
    description: str,
    priority: int,
    due_at: datetime | None,
    tag_names: list[str],
) -> Task:
    columns = await list_columns(session, board_id)
    active_columns = [col for col in columns if not col.is_done]
    target_column = active_columns[0] if active_columns else columns[0]

    task = Task(
        board_id=board_id,
        column_id=target_column.id,
        title=title.strip(),
        description=description.strip(),
        priority=max(1, min(priority, 3)),
        due_at=due_at,
        reminder_at=next_reminder_at(due_at),
        status="active",
    )
    tags = await _upsert_tags(session, board_id, tag_names)
    task.tags = tags
    session.add(task)
    await session.flush()
    return task


async def get_task(session: AsyncSession, board_id: int, task_id: int) -> Task:
    result = await session.execute(
        select(Task)
        .options(selectinload(Task.tags), selectinload(Task.column))
        .where(Task.board_id == board_id, Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise ValueError("Задача не найдена")
    return task


async def move_task(session: AsyncSession, board_id: int, task_id: int, column: BoardColumn) -> Task:
    task = await get_task(session, board_id, task_id)
    task.column_id = column.id
    if column.is_done:
        task.status = "done"
        task.completed_at = datetime.now(UTC)
    else:
        task.status = "active"
        task.completed_at = None
    await session.flush()
    return task


async def mark_task_done(session: AsyncSession, board_id: int, task_id: int) -> Task:
    done_column = await get_done_column(session, board_id)
    return await move_task(session, board_id, task_id, done_column)


async def postpone_task(session: AsyncSession, board_id: int, task_id: int, hours: int = 24) -> Task:
    task = await get_task(session, board_id, task_id)
    base = task.due_at or datetime.now(UTC)
    task.due_at = base + timedelta(hours=hours)
    task.reminder_at = next_reminder_at(task.due_at)
    await session.flush()
    return task


async def edit_task_title(session: AsyncSession, board_id: int, task_id: int, new_title: str) -> Task:
    task = await get_task(session, board_id, task_id)
    task.title = new_title.strip()
    await session.flush()
    return task


async def delete_task(session: AsyncSession, board_id: int, task_id: int) -> None:
    task = await get_task(session, board_id, task_id)
    await session.delete(task)
    await session.flush()


async def update_task_tags(session: AsyncSession, board_id: int, task_id: int, tag_names: list[str]) -> Task:
    task = await get_task(session, board_id, task_id)
    tags = await _upsert_tags(session, board_id, tag_names)
    task.tags = tags
    await session.flush()
    return task


async def list_board_tasks(session: AsyncSession, board_id: int, include_done: bool = True) -> list[Task]:
    stmt = (
        select(Task)
        .options(selectinload(Task.tags), selectinload(Task.column))
        .where(Task.board_id == board_id)
        .order_by(Task.priority.asc(), Task.due_at.asc().nullslast(), Task.created_at.desc())
    )
    if not include_done:
        stmt = stmt.where(Task.completed_at.is_(None))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def grouped_tasks_by_column(session: AsyncSession, board_id: int) -> dict[int, list[Task]]:
    tasks = await list_board_tasks(session, board_id)
    grouped: dict[int, list[Task]] = defaultdict(list)
    for task in tasks:
        if task.column_id is not None:
            grouped[task.column_id].append(task)
    return grouped


async def list_today_tasks(session: AsyncSession, board_id: int, timezone_name: str) -> list[Task]:
    start_utc, end_utc = local_day_bounds_utc(timezone_name)
    result = await session.execute(
        select(Task)
        .options(selectinload(Task.tags), selectinload(Task.column))
        .where(
            Task.board_id == board_id,
            Task.completed_at.is_(None),
            Task.due_at.is_not(None),
            Task.due_at >= start_utc,
            Task.due_at < end_utc,
        )
        .order_by(Task.due_at.asc())
    )
    return list(result.scalars().all())


async def list_overdue_tasks(session: AsyncSession, board_id: int, timezone_name: str) -> list[Task]:
    start_utc, _ = local_day_bounds_utc(timezone_name)
    result = await session.execute(
        select(Task)
        .options(selectinload(Task.tags), selectinload(Task.column))
        .where(
            Task.board_id == board_id,
            Task.completed_at.is_(None),
            Task.due_at.is_not(None),
            Task.due_at < start_utc,
        )
        .order_by(Task.due_at.asc())
    )
    return list(result.scalars().all())


async def search_tasks(session: AsyncSession, board_id: int, text: str) -> list[Task]:
    query = f"%{text.strip()}%"
    result = await session.execute(
        select(Task)
        .options(selectinload(Task.tags), selectinload(Task.column))
        .where(
            Task.board_id == board_id,
            or_(Task.title.ilike(query), Task.description.ilike(query)),
        )
        .order_by(Task.updated_at.desc())
        .limit(30)
    )
    return list(result.scalars().all())


async def list_tag_stats(session: AsyncSession, board_id: int) -> list[tuple[str, int]]:
    result = await session.execute(
        select(Tag.name, func.count(Task.id))
        .join(Tag.tasks)
        .where(Tag.board_id == board_id)
        .group_by(Tag.name)
        .order_by(func.count(Task.id).desc(), Tag.name.asc())
    )
    return [(name, count) for name, count in result.all()]
