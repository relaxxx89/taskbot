from __future__ import annotations

import pytest

from app.services.user_board_service import bootstrap_user_board


@pytest.mark.asyncio
async def test_bootstrap_user_board_returns_created_flag(session_factory) -> None:
    async with session_factory() as session:
        user1, board1, columns1, created1 = await bootstrap_user_board(
            session,
            telegram_id=555,
            tz_default="Europe/Moscow",
        )
        await session.commit()

    assert created1 is True
    assert user1.telegram_id == 555
    assert board1.owner_id == user1.id
    assert len(columns1) == 4

    async with session_factory() as session:
        user2, board2, columns2, created2 = await bootstrap_user_board(
            session,
            telegram_id=555,
            tz_default="Europe/Moscow",
        )

    assert created2 is False
    assert user2.id == user1.id
    assert board2.id == board1.id
    assert len(columns2) == 4
