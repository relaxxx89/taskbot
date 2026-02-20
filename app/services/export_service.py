from __future__ import annotations

import csv
import io
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import BoardColumn, ExportLog, Task
from app.utils.datetime_utils import format_dt


def render_markdown(columns: list[BoardColumn], tasks_by_column: dict[int, list[Task]], timezone_name: str) -> str:
    lines = ["# Экспорт задач", ""]
    for column in columns:
        lines.append(f"## {column.name}")
        tasks = tasks_by_column.get(column.id, [])
        if not tasks:
            lines.append("- _(пусто)_")
            lines.append("")
            continue

        for task in tasks:
            tags = ", ".join(sorted(tag.name for tag in task.tags)) if task.tags else ""
            meta = [f"priority={task.priority}"]
            if task.due_at:
                meta.append(f"due={format_dt(task.due_at, timezone_name)}")
            if tags:
                meta.append(f"tags={tags}")
            lines.append(f"- [{task.id}] {task.title} ({'; '.join(meta)})")
            if task.description:
                lines.append(f"  - {task.description}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_csv(tasks: list[Task], timezone_name: str) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "title", "description", "priority", "status", "column", "due_at", "tags"])
    for task in tasks:
        tags = ",".join(sorted(tag.name for tag in task.tags))
        writer.writerow(
            [
                task.id,
                task.title,
                task.description,
                task.priority,
                task.status,
                task.column.name if task.column else "",
                format_dt(task.due_at, timezone_name) if task.due_at else "",
                tags,
            ]
        )
    return output.getvalue()


async def build_export_payload(
    session: AsyncSession,
    *,
    board_id: int,
    timezone_name: str,
    user_id: int,
) -> tuple[str, str, str, str]:
    columns_result = await session.execute(
        select(BoardColumn).where(BoardColumn.board_id == board_id).order_by(BoardColumn.position)
    )
    columns = list(columns_result.scalars().all())

    tasks_result = await session.execute(
        select(Task)
        .options(selectinload(Task.tags), selectinload(Task.column))
        .where(Task.board_id == board_id)
        .order_by(Task.priority.asc(), Task.due_at.asc().nullslast(), Task.created_at.desc())
    )
    tasks = list(tasks_result.scalars().all())

    tasks_by_column: dict[int, list[Task]] = {column.id: [] for column in columns}
    for task in tasks:
        if task.column_id is not None:
            tasks_by_column.setdefault(task.column_id, []).append(task)

    md = render_markdown(columns, tasks_by_column, timezone_name)
    csv_data = render_csv(tasks, timezone_name)

    stamp = datetime.now().strftime("%Y%m%d")
    md_name = f"tasks-{stamp}.md"
    csv_name = f"tasks-{stamp}.csv"

    session.add(ExportLog(user_id=user_id, format="md", file_path=md_name))
    session.add(ExportLog(user_id=user_id, format="csv", file_path=csv_name))
    await session.flush()

    return md_name, md, csv_name, csv_data
