from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Board, BoardColumn, Task, User

_DEFAULT_COLUMNS = [
    ("Inbox", False),
    ("Todo", False),
    ("Doing", False),
    ("Done", True),
]


async def get_or_create_user(session: AsyncSession, telegram_id: int, tz_default: str) -> User:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if user:
        return user

    user = User(telegram_id=telegram_id, timezone=tz_default)
    session.add(user)
    await session.flush()
    return user


async def get_or_create_board(session: AsyncSession, user_id: int) -> Board:
    result = await session.execute(select(Board).where(Board.owner_id == user_id))
    board = result.scalar_one_or_none()
    if board:
        return board

    board = Board(owner_id=user_id, name="Моя доска")
    session.add(board)
    await session.flush()
    return board


async def ensure_default_columns(session: AsyncSession, board_id: int) -> list[BoardColumn]:
    result = await session.execute(select(BoardColumn).where(BoardColumn.board_id == board_id).order_by(BoardColumn.position))
    columns = list(result.scalars().all())
    if columns:
        return columns

    for idx, (name, is_done) in enumerate(_DEFAULT_COLUMNS):
        session.add(BoardColumn(board_id=board_id, name=name, position=idx, is_done=is_done))
    await session.flush()

    result = await session.execute(select(BoardColumn).where(BoardColumn.board_id == board_id).order_by(BoardColumn.position))
    return list(result.scalars().all())


async def bootstrap_user_board(
    session: AsyncSession,
    telegram_id: int,
    tz_default: str,
) -> tuple[User, Board, list[BoardColumn]]:
    user = await get_or_create_user(session, telegram_id, tz_default)
    board = await get_or_create_board(session, user.id)
    columns = await ensure_default_columns(session, board.id)
    return user, board, columns


async def list_columns(session: AsyncSession, board_id: int) -> list[BoardColumn]:
    result = await session.execute(select(BoardColumn).where(BoardColumn.board_id == board_id).order_by(BoardColumn.position))
    return list(result.scalars().all())


async def get_done_column(session: AsyncSession, board_id: int) -> BoardColumn:
    result = await session.execute(
        select(BoardColumn).where(BoardColumn.board_id == board_id, BoardColumn.is_done.is_(True)).order_by(BoardColumn.position)
    )
    column = result.scalar_one_or_none()
    if column:
        return column

    columns = await list_columns(session, board_id)
    fallback = columns[-1]
    fallback.is_done = True
    await session.flush()
    return fallback


async def create_column(session: AsyncSession, board_id: int, name: str) -> BoardColumn:
    position_query: Select[tuple[int | None]] = select(func.max(BoardColumn.position)).where(BoardColumn.board_id == board_id)
    max_position = (await session.execute(position_query)).scalar_one()
    column = BoardColumn(board_id=board_id, name=name.strip(), position=(max_position or 0) + 1)
    session.add(column)
    await session.flush()
    return column


async def rename_column(session: AsyncSession, board_id: int, column_id: int, new_name: str) -> BoardColumn:
    result = await session.execute(
        select(BoardColumn).where(BoardColumn.board_id == board_id, BoardColumn.id == column_id)
    )
    column = result.scalar_one_or_none()
    if column is None:
        raise ValueError("Колонка не найдена")
    column.name = new_name.strip()
    await session.flush()
    return column


async def reorder_column(session: AsyncSession, board_id: int, column_id: int, new_position: int) -> list[BoardColumn]:
    columns = await list_columns(session, board_id)
    idx = next((i for i, col in enumerate(columns) if col.id == column_id), None)
    if idx is None:
        raise ValueError("Колонка не найдена")

    column = columns.pop(idx)
    target_index = max(0, min(new_position, len(columns)))
    columns.insert(target_index, column)

    for i, col in enumerate(columns):
        col.position = 1000 + i
    await session.flush()

    for i, col in enumerate(columns):
        col.position = i
    await session.flush()
    return columns


async def delete_column(session: AsyncSession, board_id: int, column_id: int) -> None:
    columns = await list_columns(session, board_id)
    if len(columns) <= 1:
        raise ValueError("Нельзя удалить последнюю колонку")

    target = next((col for col in columns if col.id == column_id), None)
    if target is None:
        raise ValueError("Колонка не найдена")

    fallback = next(col for col in columns if col.id != column_id)
    fallback_status = "done" if fallback.is_done else "active"
    fallback_completed_at = func.now() if fallback.is_done else None
    await session.execute(
        Task.__table__
        .update()
        .where(Task.column_id == column_id)
        .values(column_id=fallback.id, status=fallback_status, completed_at=fallback_completed_at)
    )

    if target.is_done and not fallback.is_done:
        fallback.is_done = True

    await session.delete(target)
    await session.flush()

    remaining = await list_columns(session, board_id)
    for i, col in enumerate(remaining):
        col.position = i
    await session.flush()


async def resolve_column(session: AsyncSession, board_id: int, token: str) -> BoardColumn:
    token = token.strip()
    if token.isdigit():
        result = await session.execute(
            select(BoardColumn).where(BoardColumn.board_id == board_id, BoardColumn.id == int(token))
        )
        column = result.scalar_one_or_none()
        if column:
            return column

    result = await session.execute(
        select(BoardColumn).where(BoardColumn.board_id == board_id, func.lower(BoardColumn.name) == token.lower())
    )
    column = result.scalar_one_or_none()
    if column is None:
        raise ValueError("Колонка не найдена")
    return column
