from __future__ import annotations

import pytest

from app.services.export_service import build_export_payload
from app.services.task_service import create_task
from app.services.user_board_service import bootstrap_user_board


@pytest.mark.asyncio
async def test_export_markdown_and_csv(session_factory) -> None:
    async with session_factory() as session:
        user, board, _, _ = await bootstrap_user_board(session, telegram_id=777, tz_default="Europe/Moscow")
        await create_task(
            session,
            board_id=board.id,
            title="Export me",
            description="desc",
            priority=1,
            due_at=None,
            tag_names=["focus"],
        )
        await session.commit()

        md_name, md_payload, csv_name, csv_payload = await build_export_payload(
            session,
            board_id=board.id,
            timezone_name=user.timezone,
            user_id=user.id,
        )

        assert md_name.startswith("tasks-") and md_name.endswith(".md")
        assert csv_name.startswith("tasks-") and csv_name.endswith(".csv")
        assert "Export me" in md_payload
        assert "focus" in md_payload
        assert "title" in csv_payload
        assert "Export me" in csv_payload
