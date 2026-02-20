from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.keyboards import board_controls_keyboard, move_task_keyboard, task_actions_keyboard
from app.bot.middlewares.auth import AuthMiddleware
from app.bot.states import NewTaskState
from app.config import Settings
from app.services.export_service import build_export_payload
from app.services.task_service import (
    create_task,
    delete_task,
    edit_task_title,
    get_task,
    grouped_tasks_by_column,
    list_board_tasks,
    list_overdue_tasks,
    list_tag_stats,
    list_today_tasks,
    mark_task_done,
    move_task,
    postpone_task,
    search_tasks,
    update_task_tags,
)
from app.services.user_board_service import (
    bootstrap_user_board,
    create_column,
    delete_column,
    list_columns,
    rename_column,
    reorder_column,
    resolve_column,
)
from app.utils.datetime_utils import format_dt, parse_due_input
from app.utils.text import chunk_lines, parse_tags

HELP_TEXT = """Команды TaskBot:
/start - инициализация профиля
/help - это сообщение
/new - создать задачу (через диалог)
/board - показать канбан
/today - задачи на сегодня
/overdue - просроченные
/move <task_id> <column_id|name> - переместить задачу
/done <task_id> - завершить задачу
/edit <task_id> <новый заголовок> - переименовать
/delete <task_id> - удалить
/tags - список тегов
/search <текст> - поиск
/timezone <Europe/Moscow> - сменить таймзону
/digest <on|off|status> - дайджест
/export - экспорт в Markdown + CSV
/settings - настройки и управление колонками
"""


def _command_args(text: str | None) -> str:
    if not text:
        return ""
    parts = text.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ""


def _task_line(task, timezone_name: str) -> str:
    tags = f" [{', '.join(sorted(tag.name for tag in task.tags))}]" if task.tags else ""
    due = f" | due {format_dt(task.due_at, timezone_name)}" if task.due_at else ""
    return f"#{task.id} P{task.priority} {task.title}{tags}{due}"


@asynccontextmanager
async def _tx(session_factory: async_sessionmaker[AsyncSession]):
    session = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def _ensure_context(
    session: AsyncSession,
    telegram_id: int,
    settings: Settings,
):
    return await bootstrap_user_board(session, telegram_id, settings.TZ_DEFAULT)


async def _render_board_text(session: AsyncSession, board_id: int, timezone_name: str) -> str:
    columns = await list_columns(session, board_id)
    grouped = await grouped_tasks_by_column(session, board_id)

    lines = ["📌 Ваша доска", ""]
    for column in columns:
        tasks = grouped.get(column.id, [])
        lines.append(f"{column.name} ({len(tasks)})")
        if not tasks:
            lines.append("  · пусто")
        for task in tasks[:20]:
            lines.append(f"  · {_task_line(task, timezone_name)}")
        lines.append("")

    return "\n".join(lines).strip()


async def _send_task_list(
    message: Message,
    title: str,
    tasks: list,
    timezone_name: str,
) -> None:
    if not tasks:
        await message.answer(f"{title}\n\nСписок пуст.")
        return

    lines = [title, ""]
    for task in tasks:
        lines.append(f"• {_task_line(task, timezone_name)}")

    chunks = chunk_lines(lines)
    for chunk in chunks:
        await message.answer(chunk)

    for task in tasks[:8]:
        await message.answer(
            f"Действия для #{task.id}",
            reply_markup=task_actions_keyboard(task.id),
        )


def build_router(settings: Settings, session_factory: async_sessionmaker[AsyncSession]) -> Router:
    router = Router()
    auth_middleware = AuthMiddleware(settings.allowed_telegram_ids)
    router.message.middleware(auth_middleware)
    router.callback_query.middleware(auth_middleware)

    @router.message(Command("start"))
    async def start_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        async with _tx(session_factory) as session:
            user, _, _ = await _ensure_context(session, message.from_user.id, settings)
            await message.answer(
                "TaskBot активирован. Используйте /new для добавления задач или /board для доски.",
                reply_markup=board_controls_keyboard(),
            )
            await message.answer(f"Таймзона: {user.timezone}. Изменить: /timezone Europe/Moscow")

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await message.answer(HELP_TEXT)

    async def start_new_flow(message: Message, state: FSMContext) -> None:
        async with _tx(session_factory) as session:
            user, board, _ = await _ensure_context(session, message.from_user.id, settings)
            await state.set_state(NewTaskState.title)
            await state.update_data(board_id=board.id, timezone=user.timezone)
        await message.answer("Введите заголовок задачи:")

    @router.message(Command("new"))
    async def new_task_handler(message: Message, state: FSMContext) -> None:
        await start_new_flow(message, state)

    @router.callback_query(F.data == "task:create")
    async def callback_create_task(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await start_new_flow(callback.message, state)

    @router.message(NewTaskState.title)
    async def new_task_title(message: Message, state: FSMContext) -> None:
        if not (message.text and message.text.strip()):
            await message.answer("Заголовок не может быть пустым. Введите заголовок:")
            return
        await state.update_data(title=message.text.strip())
        await state.set_state(NewTaskState.description)
        await message.answer("Описание (или '-' чтобы пропустить):")

    @router.message(NewTaskState.description)
    async def new_task_description(message: Message, state: FSMContext) -> None:
        description = "" if message.text is None or message.text.strip() == "-" else message.text.strip()
        await state.update_data(description=description)
        await state.set_state(NewTaskState.due_at)
        await message.answer("Дедлайн (YYYY-MM-DD HH:MM или DD.MM.YYYY HH:MM, '-' чтобы пропустить):")

    @router.message(NewTaskState.due_at)
    async def new_task_due(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        timezone_name = data["timezone"]
        raw = message.text or ""
        try:
            due_at = parse_due_input(raw, timezone_name)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        await state.update_data(due_at=due_at.isoformat() if due_at else "")
        await state.set_state(NewTaskState.priority)
        await message.answer("Приоритет (1 = высокий, 2 = средний, 3 = низкий):")

    @router.message(NewTaskState.priority)
    async def new_task_priority(message: Message, state: FSMContext) -> None:
        raw = (message.text or "").strip()
        if not raw.isdigit() or int(raw) not in {1, 2, 3}:
            await message.answer("Введите 1, 2 или 3")
            return
        await state.update_data(priority=int(raw))
        await state.set_state(NewTaskState.tags)
        await message.answer("Теги через запятую (или '-' чтобы пропустить):")

    @router.message(NewTaskState.tags)
    async def new_task_tags(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        due_at = datetime.fromisoformat(data["due_at"]) if data.get("due_at") else None
        tags = parse_tags(message.text or "")

        async with _tx(session_factory) as session:
            task = await create_task(
                session,
                board_id=data["board_id"],
                title=data["title"],
                description=data.get("description", ""),
                priority=data.get("priority", 2),
                due_at=due_at,
                tag_names=tags,
            )

        await state.clear()
        due_info = format_dt(task.due_at, data["timezone"]) if task.due_at else "без срока"
        await message.answer(
            f"✅ Создана задача #{task.id}: {task.title}\nПриоритет: P{task.priority}\nСрок: {due_info}",
            reply_markup=task_actions_keyboard(task.id),
        )

    @router.message(Command("board"))
    async def board_handler(message: Message) -> None:
        async with _tx(session_factory) as session:
            user, board, _ = await _ensure_context(session, message.from_user.id, settings)
            board_text = await _render_board_text(session, board.id, user.timezone)
        await message.answer(board_text, reply_markup=board_controls_keyboard())

    @router.message(Command("today"))
    async def today_handler(message: Message) -> None:
        async with _tx(session_factory) as session:
            user, board, _ = await _ensure_context(session, message.from_user.id, settings)
            tasks = await list_today_tasks(session, board.id, user.timezone)
        await _send_task_list(message, "📅 Сегодня", tasks, user.timezone)

    @router.message(Command("overdue"))
    async def overdue_handler(message: Message) -> None:
        async with _tx(session_factory) as session:
            user, board, _ = await _ensure_context(session, message.from_user.id, settings)
            tasks = await list_overdue_tasks(session, board.id, user.timezone)
        await _send_task_list(message, "🚨 Просроченные", tasks, user.timezone)

    @router.callback_query(F.data.startswith("filter:set:"))
    async def filter_set_handler(callback: CallbackQuery) -> None:
        scope = callback.data.split(":", maxsplit=2)[2]
        async with _tx(session_factory) as session:
            user, board, _ = await _ensure_context(session, callback.from_user.id, settings)
            if scope == "today":
                tasks = await list_today_tasks(session, board.id, user.timezone)
                await callback.message.answer("Фильтр: сегодня")
                await _send_task_list(callback.message, "📅 Сегодня", tasks, user.timezone)
            elif scope == "overdue":
                tasks = await list_overdue_tasks(session, board.id, user.timezone)
                await callback.message.answer("Фильтр: просроченные")
                await _send_task_list(callback.message, "🚨 Просроченные", tasks, user.timezone)
            else:
                board_text = await _render_board_text(session, board.id, user.timezone)
                await callback.message.answer(board_text, reply_markup=board_controls_keyboard())
        await callback.answer()

    @router.message(Command("move"))
    async def move_handler(message: Message) -> None:
        args = _command_args(message.text)
        parts = args.split(maxsplit=1)
        if len(parts) != 2 or not parts[0].isdigit():
            await message.answer("Использование: /move <task_id> <column_id|column_name>")
            return

        task_id = int(parts[0])
        column_token = parts[1]

        async with _tx(session_factory) as session:
            _, board, _ = await _ensure_context(session, message.from_user.id, settings)
            column = await resolve_column(session, board.id, column_token)
            task = await move_task(session, board.id, task_id, column)

        await message.answer(f"↔ Задача #{task.id} перемещена в {column.name}")

    @router.message(Command("done"))
    async def done_handler(message: Message) -> None:
        args = _command_args(message.text)
        if not args.isdigit():
            await message.answer("Использование: /done <task_id>")
            return

        async with _tx(session_factory) as session:
            _, board, _ = await _ensure_context(session, message.from_user.id, settings)
            task = await mark_task_done(session, board.id, int(args))

        await message.answer(f"✅ Задача #{task.id} завершена")

    @router.message(Command("edit"))
    async def edit_handler(message: Message) -> None:
        args = _command_args(message.text)
        parts = args.split(maxsplit=1)
        if len(parts) != 2 or not parts[0].isdigit():
            await message.answer("Использование: /edit <task_id> <новый заголовок>")
            return

        async with _tx(session_factory) as session:
            _, board, _ = await _ensure_context(session, message.from_user.id, settings)
            task = await edit_task_title(session, board.id, int(parts[0]), parts[1])

        await message.answer(f"✏️ Задача #{task.id} обновлена: {task.title}")

    @router.message(Command("delete"))
    async def delete_handler(message: Message) -> None:
        args = _command_args(message.text)
        if not args.isdigit():
            await message.answer("Использование: /delete <task_id>")
            return

        task_id = int(args)
        async with _tx(session_factory) as session:
            _, board, _ = await _ensure_context(session, message.from_user.id, settings)
            await delete_task(session, board.id, task_id)

        await message.answer(f"🗑 Задача #{task_id} удалена")

    @router.message(Command("tags"))
    async def tags_handler(message: Message) -> None:
        async with _tx(session_factory) as session:
            _, board, _ = await _ensure_context(session, message.from_user.id, settings)
            stats = await list_tag_stats(session, board.id)

        if not stats:
            await message.answer("Тегов пока нет")
            return

        lines = ["🏷 Теги", ""]
        lines.extend(f"• {name}: {count}" for name, count in stats)
        await message.answer("\n".join(lines))

    @router.message(Command("search"))
    async def search_handler(message: Message) -> None:
        query = _command_args(message.text)
        if not query:
            await message.answer("Использование: /search <текст>")
            return

        async with _tx(session_factory) as session:
            user, board, _ = await _ensure_context(session, message.from_user.id, settings)
            tasks = await search_tasks(session, board.id, query)

        await _send_task_list(message, f"🔍 Поиск: {query}", tasks, user.timezone)

    @router.message(Command("timezone"))
    async def timezone_handler(message: Message) -> None:
        arg = _command_args(message.text)
        async with _tx(session_factory) as session:
            user, _, _ = await _ensure_context(session, message.from_user.id, settings)
            if not arg:
                await message.answer(f"Текущая таймзона: {user.timezone}")
                return

            try:
                ZoneInfo(arg)
            except ZoneInfoNotFoundError:
                await message.answer("Неверная таймзона. Пример: Europe/Moscow")
                return

            user.timezone = arg
            await message.answer(f"✅ Таймзона обновлена: {arg}")

    @router.message(Command("digest"))
    async def digest_handler(message: Message) -> None:
        arg = _command_args(message.text).lower().strip()
        async with _tx(session_factory) as session:
            user, _, _ = await _ensure_context(session, message.from_user.id, settings)
            if not arg or arg == "status":
                status = "on" if user.digest_enabled else "off"
                await message.answer(f"Дайджест: {status}")
                return
            if arg not in {"on", "off"}:
                await message.answer("Использование: /digest <on|off|status>")
                return

            user.digest_enabled = arg == "on"
            await message.answer(f"✅ Дайджест: {arg}")

    async def send_export(message: Message) -> None:
        async with _tx(session_factory) as session:
            user, board, _ = await _ensure_context(session, message.from_user.id, settings)
            md_name, md_payload, csv_name, csv_payload = await build_export_payload(
                session,
                board_id=board.id,
                timezone_name=user.timezone,
                user_id=user.id,
            )

        await message.answer_document(
            BufferedInputFile(md_payload.encode("utf-8"), filename=md_name),
            caption="Markdown экспорт",
        )
        await message.answer_document(
            BufferedInputFile(csv_payload.encode("utf-8"), filename=csv_name),
            caption="CSV экспорт",
        )

    @router.message(Command("export"))
    async def export_handler(message: Message) -> None:
        await send_export(message)

    @router.callback_query(F.data == "export:run")
    async def export_callback_handler(callback: CallbackQuery) -> None:
        await callback.answer()
        await send_export(callback.message)

    @router.message(Command("settings"))
    async def settings_handler(message: Message) -> None:
        args = _command_args(message.text)
        async with _tx(session_factory) as session:
            user, board, columns = await _ensure_context(session, message.from_user.id, settings)
            if not args:
                lines = [
                    "⚙️ Настройки",
                    f"Таймзона: {user.timezone}",
                    f"Дайджест: {'on' if user.digest_enabled else 'off'}",
                    "",
                    "Колонки:",
                ]
                lines.extend(
                    f"• id={column.id} pos={column.position} name={column.name}{' [DONE]' if column.is_done else ''}"
                    for column in columns
                )
                lines.extend(
                    [
                        "",
                        "Команды колонок:",
                        "/settings addcol <name>",
                        "/settings renamecol <id> <name>",
                        "/settings movecol <id> <position>",
                        "/settings delcol <id>",
                    ]
                )
                await message.answer("\n".join(lines))
                return

            parts = args.split(maxsplit=2)
            action = parts[0].lower()
            if action == "addcol" and len(parts) >= 2:
                column = await create_column(session, board.id, parts[1])
                await message.answer(f"✅ Колонка создана: {column.name} (id={column.id})")
                return

            if action == "renamecol" and len(parts) == 3 and parts[1].isdigit():
                column = await rename_column(session, board.id, int(parts[1]), parts[2])
                await message.answer(f"✅ Колонка переименована: {column.name}")
                return

            if action == "movecol" and len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
                await reorder_column(session, board.id, int(parts[1]), int(parts[2]))
                await message.answer("✅ Порядок колонок обновлен")
                return

            if action == "delcol" and len(parts) >= 2 and parts[1].isdigit():
                await delete_column(session, board.id, int(parts[1]))
                await message.answer("✅ Колонка удалена")
                return

            await message.answer("Неверная команда settings. См. /settings")

    @router.callback_query(F.data.startswith("task:done:"))
    async def callback_done(callback: CallbackQuery) -> None:
        task_id = int(callback.data.split(":", maxsplit=2)[2])
        async with _tx(session_factory) as session:
            _, board, _ = await _ensure_context(session, callback.from_user.id, settings)
            await mark_task_done(session, board.id, task_id)
        await callback.answer("Готово")
        await callback.message.answer(f"✅ Задача #{task_id} завершена")

    @router.callback_query(F.data.startswith("task:move:"))
    async def callback_move(callback: CallbackQuery) -> None:
        task_id = int(callback.data.split(":", maxsplit=2)[2])
        async with _tx(session_factory) as session:
            _, board, columns = await _ensure_context(session, callback.from_user.id, settings)
            await get_task(session, board.id, task_id)
        await callback.answer()
        await callback.message.answer(
            f"Выберите колонку для задачи #{task_id}",
            reply_markup=move_task_keyboard(task_id, columns),
        )

    @router.callback_query(F.data.startswith("column:switch:"))
    async def callback_column_switch(callback: CallbackQuery) -> None:
        _, _, task_id_raw, column_id_raw = callback.data.split(":", maxsplit=3)
        task_id = int(task_id_raw)
        column_id = int(column_id_raw)

        async with _tx(session_factory) as session:
            _, board, _ = await _ensure_context(session, callback.from_user.id, settings)
            columns = await list_columns(session, board.id)
            column = next((item for item in columns if item.id == column_id), None)
            if column is None:
                await callback.answer("Колонка не найдена", show_alert=True)
                return
            await move_task(session, board.id, task_id, column)

        await callback.answer("Перемещено")
        await callback.message.answer(f"↔ Задача #{task_id} -> {column.name}")

    @router.callback_query(F.data.startswith("task:postpone:"))
    async def callback_postpone(callback: CallbackQuery) -> None:
        task_id = int(callback.data.split(":", maxsplit=2)[2])
        async with _tx(session_factory) as session:
            user, board, _ = await _ensure_context(session, callback.from_user.id, settings)
            task = await postpone_task(session, board.id, task_id)
        await callback.answer("Отложено")
        await callback.message.answer(
            f"⏭ Задача #{task.id} перенесена до {format_dt(task.due_at, user.timezone)}"
        )

    @router.message(Command("settags"))
    async def set_tags_command(message: Message) -> None:
        args = _command_args(message.text)
        parts = args.split(maxsplit=1)
        if len(parts) != 2 or not parts[0].isdigit():
            await message.answer("Использование: /settags <task_id> <tag1,tag2>")
            return

        task_id = int(parts[0])
        tag_names = parse_tags(parts[1])
        async with _tx(session_factory) as session:
            _, board, _ = await _ensure_context(session, message.from_user.id, settings)
            task = await update_task_tags(session, board.id, task_id, tag_names)

        await message.answer(f"🏷 Теги обновлены для #{task.id}")

    @router.message(F.text)
    async def fallback_text(message: Message) -> None:
        await message.answer("Не понял команду. Используйте /help")

    return router
