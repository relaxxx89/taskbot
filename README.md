# Personal Telegram TaskBot (Kanban)

Telegram-бот для личного менеджмента задач в стиле канбан-доски с деплоем через Docker Compose.

## Возможности v1

- Personal-first доступ только по whitelist Telegram ID.
- Одна доска с кастомными колонками.
- Полный набор команд: `/start`, `/help`, `/new`, `/board`, `/today`, `/overdue`, `/move`, `/done`, `/edit`, `/delete`, `/tags`, `/search`, `/timezone`, `/digest`, `/export`, `/settings`.
- Inline callback actions: `task:create`, `task:move`, `task:done`, `task:postpone`, `column:switch`, `filter:set`, `export:run`.
- Напоминания по дедлайнам и ежедневный дайджест (по умолчанию 09:00).
- Экспорт задач в Markdown и CSV.
- Health endpoint: `GET /health`.

## Быстрый старт

1. Создайте Telegram-бота через [@BotFather](https://t.me/BotFather) и получите token.
2. Узнайте ваш Telegram ID (например через [@userinfobot](https://t.me/userinfobot)).
3. Скопируйте `.env.example` в `.env` и заполните значения.
4. Запустите сервисы:

```bash
docker compose up -d --build
```

5. Проверьте логи приложения:

```bash
docker compose logs -f app
```

6. Проверьте health:

```bash
curl http://localhost:8080/health
```

## Важные переменные `.env`

- `BOT_TOKEN` — токен Telegram-бота.
- `ALLOWED_TELEGRAM_IDS` — список допустимых Telegram ID через запятую.
- `DATABASE_URL` — async SQLAlchemy URL (`postgresql+asyncpg://...`).
- `REDIS_URL` — Redis URL.
- `TZ_DEFAULT` — таймзона по умолчанию для нового пользователя.
- `DIGEST_TIME` — ежедневный дайджест в формате `HH:MM`.
- `BACKUP_RETENTION_DAYS` — сколько дней хранить бэкапы.

## Команды бота

- `/new` — пошаговое создание задачи.
- `/board` — обзор доски по колонкам.
- `/today` — задачи на сегодня.
- `/overdue` — просроченные задачи.
- `/move <task_id> <column_id|name>` — перенос.
- `/done <task_id>` — завершить.
- `/edit <task_id> <new title>` — переименовать.
- `/delete <task_id>` — удалить.
- `/tags` — статистика тегов.
- `/search <text>` — поиск.
- `/timezone <IANA zone>` — сменить таймзону, например `Europe/Moscow`.
- `/digest <on|off|status>` — настройка дайджеста.
- `/export` — получить Markdown и CSV.
- `/settings` — управление колонками.

## Миграции

```bash
docker compose exec app alembic upgrade head
```

## Тесты

Локально:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

## Состав Docker Compose

- `app` — aiogram + FastAPI + APScheduler.
- `postgres` — основная БД.
- `redis` — FSM/session storage.
- `backup` — ежедневный `pg_dump` в volume.

## Ограничения v1

- Нет recurring-задач.
- Один пользователь, одна доска.
- Работа через long polling (без webhook).
