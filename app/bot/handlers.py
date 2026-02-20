from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.keyboards import (
    board_controls_keyboard,
    main_reply_keyboard,
    move_task_keyboard,
    new_task_due_keyboard,
    new_task_nav_keyboard,
    post_create_edit_keyboard,
    task_actions_keyboard,
    task_priority_keyboard,
    timezone_quick_keyboard,
    timezone_settings_keyboard,
)
from app.bot.middlewares.auth import AuthMiddleware
from app.bot.states import EditTaskState, NewTaskState
from app.config import Settings
from app.services.export_service import build_export_payload
from app.services.task_service import (
    create_task,
    delete_task,
    edit_task_title,
    get_task,
    grouped_tasks_by_column,
    list_overdue_tasks,
    list_tag_stats,
    list_today_tasks,
    mark_task_done,
    move_task,
    postpone_task,
    search_tasks,
    update_task_description,
    update_task_priority,
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
from app.utils.datetime_utils import format_dt, parse_due_input, utcnow
from app.utils.text import chunk_lines, parse_tags

HELP_TEXT = """TaskBot: быстрый режим

Основное:
/start - старт и главное меню
/new - быстрое создание задачи
/board - доска
/today - сегодня
/overdue - просрочено
/export - экспорт MD/CSV
/settings - настройки

Дополнительно:
/move <task_id> <column_id|name>
/done <task_id>
/edit <task_id> <новый заголовок>
/delete <task_id>
/tags
/search <текст>
/timezone <Europe/Moscow>
/digest <on|off|status>

Дедлайн можно вводить так:
завтра 10:00, через 2 дня, +3d, +6h, 2026-03-01 14:30
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


async def _ensure_context(session: AsyncSession, telegram_id: int, settings: Settings):
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


async def _send_task_list(message: Message, title: str, tasks: list, timezone_name: str) -> None:
    if not tasks:
        await message.answer(f"{title}\n\nСписок пуст.")
        return

    lines = [title, ""]
    for task in tasks:
        lines.append(f"• {_task_line(task, timezone_name)}")

    for chunk in chunk_lines(lines):
        await message.answer(chunk)

    for task in tasks[:8]:
        await message.answer(f"Действия для #{task.id}", reply_markup=task_actions_keyboard(task.id))


def _due_from_preset(preset: str, timezone_name: str) -> datetime | None:
    tz = ZoneInfo(timezone_name)
    local_now = utcnow().astimezone(tz)

    if preset == "none":
        return None

    if preset == "today18":
        local_due = datetime.combine(local_now.date(), datetime.min.time(), tzinfo=tz).replace(hour=18)
        return local_due.astimezone(UTC)

    if preset == "tomorrow10":
        target_date = (local_now + timedelta(days=1)).date()
        local_due = datetime.combine(target_date, datetime.min.time(), tzinfo=tz).replace(hour=10)
        return local_due.astimezone(UTC)

    if preset == "plus3d":
        target_date = (local_now + timedelta(days=3)).date()
        local_due = datetime.combine(target_date, datetime.min.time(), tzinfo=tz).replace(hour=10)
        return local_due.astimezone(UTC)

    raise ValueError("unknown due preset")


async def _complete_new_task(
    message: Message,
    state: FSMContext,
    session_factory: async_sessionmaker[AsyncSession],
    due_at: datetime | None,
) -> None:
    data = await state.get_data()
    title = data.get("title", "").strip()
    board_id = data.get("board_id")
    timezone_name = data.get("timezone", "UTC")

    if not title or board_id is None:
        await state.clear()
        await message.answer("Не удалось завершить создание задачи, попробуйте ещё раз через /new")
        return

    async with _tx(session_factory) as session:
        task = await create_task(
            session,
            board_id=board_id,
            title=title,
            description="",
            priority=2,
            due_at=due_at,
            tag_names=[],
        )

    await state.clear()
    due_info = format_dt(task.due_at, timezone_name) if task.due_at else "без срока"
    await message.answer(
        f"✅ Создана задача #{task.id}: {task.title}\nПриоритет: P{task.priority}\nСрок: {due_info}",
        reply_markup=post_create_edit_keyboard(task.id),
    )


def _settings_overview(user, columns: list) -> str:
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
    return "\n".join(lines)


async def _show_settings(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    user_id: int,
) -> None:
    async with _tx(session_factory) as session:
        user, _, columns, _ = await _ensure_context(session, user_id, settings)
        text = _settings_overview(user, columns)
    await message.answer(text, reply_markup=timezone_settings_keyboard())


def build_router(settings: Settings, session_factory: async_sessionmaker[AsyncSession]) -> Router:
    router = Router()
    auth_middleware = AuthMiddleware(settings.allowed_telegram_ids)
    router.message.middleware(auth_middleware)
    router.callback_query.middleware(auth_middleware)

    async def start_new_flow(message: Message, state: FSMContext, user_id: int) -> None:
        async with _tx(session_factory) as session:
            user, board, _, _ = await _ensure_context(session, user_id, settings)
            await state.set_state(NewTaskState.title)
            await state.update_data(board_id=board.id, timezone=user.timezone)
        await message.answer("Введите заголовок задачи:", reply_markup=new_task_nav_keyboard())

    async def send_board(message: Message, user_id: int) -> None:
        async with _tx(session_factory) as session:
            user, board, _, _ = await _ensure_context(session, user_id, settings)
            board_text = await _render_board_text(session, board.id, user.timezone)
        await message.answer(board_text, reply_markup=board_controls_keyboard())

    async def send_today(message: Message, user_id: int) -> None:
        async with _tx(session_factory) as session:
            user, board, _, _ = await _ensure_context(session, user_id, settings)
            tasks = await list_today_tasks(session, board.id, user.timezone)
        await _send_task_list(message, "📅 Сегодня", tasks, user.timezone)

    async def send_overdue(message: Message, user_id: int) -> None:
        async with _tx(session_factory) as session:
            user, board, _, _ = await _ensure_context(session, user_id, settings)
            tasks = await list_overdue_tasks(session, board.id, user.timezone)
        await _send_task_list(message, "🚨 Просроченные", tasks, user.timezone)

    async def send_export(message: Message, user_id: int) -> None:
        async with _tx(session_factory) as session:
            user, board, _, _ = await _ensure_context(session, user_id, settings)
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

    @router.message(Command("start"))
    async def start_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        async with _tx(session_factory) as session:
            user, _, _, created = await _ensure_context(session, message.from_user.id, settings)

        text = "TaskBot активирован. Используйте кнопки ниже для быстрого управления задачами."
        if created:
            text += f"\n\nТаймзона: {user.timezone}. Сменить можно в ⚙️ Настройки."
        await message.answer(text, reply_markup=main_reply_keyboard())

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await message.answer(HELP_TEXT)

    @router.message(Command("new"))
    async def new_task_handler(message: Message, state: FSMContext) -> None:
        await start_new_flow(message, state, message.from_user.id)

    @router.callback_query(F.data == "task:create")
    async def callback_create_task(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await start_new_flow(callback.message, state, callback.from_user.id)

    @router.message(NewTaskState.title)
    async def new_task_title(message: Message, state: FSMContext) -> None:
        if not (message.text and message.text.strip()):
            await message.answer("Заголовок не может быть пустым. Введите заголовок:", reply_markup=new_task_nav_keyboard())
            return

        await state.update_data(title=message.text.strip())
        await state.set_state(NewTaskState.due_choice)
        await message.answer("Выберите дедлайн:", reply_markup=new_task_due_keyboard())

    @router.callback_query(NewTaskState.due_choice, F.data.startswith("task:due:"))
    async def new_task_due_preset(callback: CallbackQuery, state: FSMContext) -> None:
        preset = callback.data.split(":", maxsplit=2)[2]
        data = await state.get_data()
        timezone_name = data.get("timezone", settings.TZ_DEFAULT)

        if preset == "custom":
            await state.set_state(NewTaskState.due_custom)
            await callback.answer()
            await callback.message.answer(
                'Введите дедлайн (например: "завтра 10:00", "через 2 дня", "+3d").',
                reply_markup=new_task_nav_keyboard(),
            )
            return

        try:
            due_at = _due_from_preset(preset, timezone_name)
        except ValueError:
            await callback.answer("Неизвестный пресет", show_alert=True)
            return

        await callback.answer("Сохранено")
        await _complete_new_task(callback.message, state, session_factory, due_at)

    @router.message(NewTaskState.due_custom)
    async def new_task_due_custom(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        timezone_name = data.get("timezone", settings.TZ_DEFAULT)
        raw = message.text or ""
        try:
            due_at = parse_due_input(raw, timezone_name)
        except ValueError as exc:
            await message.answer(str(exc), reply_markup=new_task_nav_keyboard())
            return

        await _complete_new_task(message, state, session_factory, due_at)

    @router.callback_query(F.data == "task:new:skip")
    async def flow_skip(callback: CallbackQuery, state: FSMContext) -> None:
        current = await state.get_state()
        if current == NewTaskState.due_custom.state:
            await callback.answer("Без срока")
            await _complete_new_task(callback.message, state, session_factory, due_at=None)
            return

        if current in {EditTaskState.tags.state, EditTaskState.description.state, EditTaskState.timezone_custom.state}:
            await state.clear()
            await callback.answer("Пропущено")
            await callback.message.answer("Ок, пропустили.")
            return

        await callback.answer("Нечего пропускать", show_alert=True)

    @router.callback_query(F.data == "task:new:cancel")
    async def flow_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await callback.answer("Отменено")
        await callback.message.answer("Действие отменено.", reply_markup=main_reply_keyboard())

    @router.message(Command("board"))
    async def board_handler(message: Message) -> None:
        await send_board(message, message.from_user.id)

    @router.message(Command("today"))
    async def today_handler(message: Message) -> None:
        await send_today(message, message.from_user.id)

    @router.message(Command("overdue"))
    async def overdue_handler(message: Message) -> None:
        await send_overdue(message, message.from_user.id)

    @router.callback_query(F.data.startswith("filter:set:"))
    async def filter_set_handler(callback: CallbackQuery) -> None:
        scope = callback.data.split(":", maxsplit=2)[2]
        await callback.answer()
        if scope == "today":
            await send_today(callback.message, callback.from_user.id)
            return
        if scope == "overdue":
            await send_overdue(callback.message, callback.from_user.id)
            return
        await send_board(callback.message, callback.from_user.id)

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
            _, board, _, _ = await _ensure_context(session, message.from_user.id, settings)
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
            _, board, _, _ = await _ensure_context(session, message.from_user.id, settings)
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
            _, board, _, _ = await _ensure_context(session, message.from_user.id, settings)
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
            _, board, _, _ = await _ensure_context(session, message.from_user.id, settings)
            await delete_task(session, board.id, task_id)

        await message.answer(f"🗑 Задача #{task_id} удалена")

    @router.message(Command("tags"))
    async def tags_handler(message: Message) -> None:
        async with _tx(session_factory) as session:
            _, board, _, _ = await _ensure_context(session, message.from_user.id, settings)
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
            user, board, _, _ = await _ensure_context(session, message.from_user.id, settings)
            tasks = await search_tasks(session, board.id, query)

        await _send_task_list(message, f"🔍 Поиск: {query}", tasks, user.timezone)

    @router.message(Command("timezone"))
    async def timezone_handler(message: Message) -> None:
        arg = _command_args(message.text)
        async with _tx(session_factory) as session:
            user, _, _, _ = await _ensure_context(session, message.from_user.id, settings)
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
            user, _, _, _ = await _ensure_context(session, message.from_user.id, settings)
            if not arg or arg == "status":
                status = "on" if user.digest_enabled else "off"
                await message.answer(f"Дайджест: {status}")
                return
            if arg not in {"on", "off"}:
                await message.answer("Использование: /digest <on|off|status>")
                return

            user.digest_enabled = arg == "on"
            await message.answer(f"✅ Дайджест: {arg}")

    @router.message(Command("export"))
    async def export_handler(message: Message) -> None:
        await send_export(message, message.from_user.id)

    @router.callback_query(F.data == "export:run")
    async def export_callback_handler(callback: CallbackQuery) -> None:
        await callback.answer()
        await send_export(callback.message, callback.from_user.id)

    @router.message(Command("settings"))
    async def settings_handler(message: Message) -> None:
        args = _command_args(message.text)
        async with _tx(session_factory) as session:
            user, board, columns, _ = await _ensure_context(session, message.from_user.id, settings)
            if not args:
                await message.answer(_settings_overview(user, columns), reply_markup=timezone_settings_keyboard())
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

    @router.callback_query(F.data == "settings:timezone")
    async def settings_timezone(callback: CallbackQuery) -> None:
        async with _tx(session_factory) as session:
            user, _, _, _ = await _ensure_context(session, callback.from_user.id, settings)
        await callback.answer()
        await callback.message.answer(
            f"Текущая таймзона: {user.timezone}\nВыберите готовую или введите вручную.",
            reply_markup=timezone_quick_keyboard(),
        )

    @router.callback_query(F.data.startswith("settings:timezone:set:"))
    async def settings_timezone_set(callback: CallbackQuery) -> None:
        timezone_name = callback.data.split(":", maxsplit=3)[3]
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            await callback.answer("Неверная таймзона", show_alert=True)
            return

        async with _tx(session_factory) as session:
            user, _, _, _ = await _ensure_context(session, callback.from_user.id, settings)
            user.timezone = timezone_name

        await callback.answer("Сохранено")
        await callback.message.answer(f"✅ Таймзона обновлена: {timezone_name}")

    @router.callback_query(F.data == "settings:timezone:custom")
    async def settings_timezone_custom(callback: CallbackQuery, state: FSMContext) -> None:
        async with _tx(session_factory) as session:
            _, board, _, _ = await _ensure_context(session, callback.from_user.id, settings)
        await state.set_state(EditTaskState.timezone_custom)
        await state.update_data(board_id=board.id)
        await callback.answer()
        await callback.message.answer(
            "Введите таймзону (например Europe/Samara):",
            reply_markup=new_task_nav_keyboard(),
        )

    @router.callback_query(F.data == "settings:timezone:back")
    async def settings_timezone_back(callback: CallbackQuery) -> None:
        await callback.answer()
        await _show_settings(callback.message, session_factory, settings, callback.from_user.id)

    @router.message(EditTaskState.timezone_custom)
    async def timezone_custom_input(message: Message, state: FSMContext) -> None:
        raw = (message.text or "").strip()
        try:
            ZoneInfo(raw)
        except ZoneInfoNotFoundError:
            await message.answer("Неверная таймзона. Пример: Europe/Moscow", reply_markup=new_task_nav_keyboard())
            return

        async with _tx(session_factory) as session:
            user, _, _, _ = await _ensure_context(session, message.from_user.id, settings)
            user.timezone = raw

        await state.clear()
        await message.answer(f"✅ Таймзона обновлена: {raw}")

    @router.callback_query(F.data.startswith("task:edit:tags:"))
    async def callback_edit_tags(callback: CallbackQuery, state: FSMContext) -> None:
        task_id = int(callback.data.split(":", maxsplit=3)[3])
        async with _tx(session_factory) as session:
            _, board, _, _ = await _ensure_context(session, callback.from_user.id, settings)
            await get_task(session, board.id, task_id)
        await state.set_state(EditTaskState.tags)
        await state.update_data(edit_task_id=task_id)
        await callback.answer()
        await callback.message.answer("Введите теги через запятую (или '-' чтобы очистить):", reply_markup=new_task_nav_keyboard())

    @router.message(EditTaskState.tags)
    async def edit_tags_input(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        task_id = int(data["edit_task_id"])
        tag_names = parse_tags(message.text or "")

        async with _tx(session_factory) as session:
            _, board, _, _ = await _ensure_context(session, message.from_user.id, settings)
            task = await update_task_tags(session, board.id, task_id, tag_names)

        await state.clear()
        await message.answer(f"🏷 Теги обновлены для #{task.id}", reply_markup=post_create_edit_keyboard(task.id))

    @router.callback_query(F.data.startswith("task:edit:description:"))
    async def callback_edit_description(callback: CallbackQuery, state: FSMContext) -> None:
        task_id = int(callback.data.split(":", maxsplit=3)[3])
        async with _tx(session_factory) as session:
            _, board, _, _ = await _ensure_context(session, callback.from_user.id, settings)
            await get_task(session, board.id, task_id)
        await state.set_state(EditTaskState.description)
        await state.update_data(edit_task_id=task_id)
        await callback.answer()
        await callback.message.answer(
            "Введите описание (или '-' чтобы очистить):",
            reply_markup=new_task_nav_keyboard(),
        )

    @router.message(EditTaskState.description)
    async def edit_description_input(message: Message, state: FSMContext) -> None:
        data = await state.get_data()
        task_id = int(data["edit_task_id"])
        description = "" if message.text is None or message.text.strip() == "-" else message.text.strip()

        async with _tx(session_factory) as session:
            _, board, _, _ = await _ensure_context(session, message.from_user.id, settings)
            task = await update_task_description(session, board.id, task_id, description)

        await state.clear()
        await message.answer(f"📝 Описание обновлено для #{task.id}", reply_markup=post_create_edit_keyboard(task.id))

    @router.callback_query(F.data.startswith("task:edit:priority:"))
    async def callback_edit_priority(callback: CallbackQuery) -> None:
        task_id = int(callback.data.split(":", maxsplit=3)[3])
        await callback.answer()
        await callback.message.answer(f"Выберите приоритет для #{task_id}", reply_markup=task_priority_keyboard(task_id))

    @router.callback_query(F.data.startswith("task:priority:set:"))
    async def callback_set_priority(callback: CallbackQuery) -> None:
        _, _, _, task_id_raw, priority_raw = callback.data.split(":", maxsplit=4)
        task_id = int(task_id_raw)
        priority = int(priority_raw)

        async with _tx(session_factory) as session:
            _, board, _, _ = await _ensure_context(session, callback.from_user.id, settings)
            task = await update_task_priority(session, board.id, task_id, priority)

        await callback.answer("Сохранено")
        await callback.message.answer(f"⚡ Приоритет задачи #{task.id}: P{task.priority}")

    @router.callback_query(F.data.startswith("task:done:"))
    async def callback_done(callback: CallbackQuery) -> None:
        task_id = int(callback.data.split(":", maxsplit=2)[2])
        async with _tx(session_factory) as session:
            _, board, _, _ = await _ensure_context(session, callback.from_user.id, settings)
            await mark_task_done(session, board.id, task_id)
        await callback.answer("Готово")
        await callback.message.answer(f"✅ Задача #{task_id} завершена")

    @router.callback_query(F.data.startswith("task:move:"))
    async def callback_move(callback: CallbackQuery) -> None:
        task_id = int(callback.data.split(":", maxsplit=2)[2])
        async with _tx(session_factory) as session:
            _, board, columns, _ = await _ensure_context(session, callback.from_user.id, settings)
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
            _, board, _, _ = await _ensure_context(session, callback.from_user.id, settings)
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
            user, board, _, _ = await _ensure_context(session, callback.from_user.id, settings)
            task = await postpone_task(session, board.id, task_id)
        await callback.answer("Отложено")
        await callback.message.answer(f"⏭ Задача #{task.id} перенесена до {format_dt(task.due_at, user.timezone)}")

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
            _, board, _, _ = await _ensure_context(session, message.from_user.id, settings)
            task = await update_task_tags(session, board.id, task_id, tag_names)

        await message.answer(f"🏷 Теги обновлены для #{task.id}")

    @router.message(F.text == "➕ Новая")
    async def quick_new(message: Message, state: FSMContext) -> None:
        await start_new_flow(message, state, message.from_user.id)

    @router.message(F.text == "📋 Доска")
    async def quick_board(message: Message) -> None:
        await send_board(message, message.from_user.id)

    @router.message(F.text == "📅 Сегодня")
    async def quick_today(message: Message) -> None:
        await send_today(message, message.from_user.id)

    @router.message(F.text == "🚨 Просрочено")
    async def quick_overdue(message: Message) -> None:
        await send_overdue(message, message.from_user.id)

    @router.message(F.text == "📦 Экспорт")
    async def quick_export(message: Message) -> None:
        await send_export(message, message.from_user.id)

    @router.message(F.text == "⚙️ Настройки")
    async def quick_settings(message: Message) -> None:
        await _show_settings(message, session_factory, settings, message.from_user.id)

    @router.message(F.text)
    async def fallback_text(message: Message) -> None:
        await message.answer("Не понял команду. Используйте /help")

    return router
