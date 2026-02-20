# Operations Runbook

## Запуск

```bash
docker compose up -d --build
```

## Проверка статуса

```bash
docker compose ps
docker compose logs -f app
curl http://localhost:8080/health
```

## Применение миграций

```bash
docker compose exec app alembic upgrade head
```

## Бэкапы

- Бэкап-контейнер создаёт `pg_dump` каждые `BACKUP_INTERVAL_SECONDS` (по умолчанию 86400).
- Файлы хранятся в `backup_data` volume.
- Старые копии удаляются по `BACKUP_RETENTION_DAYS`.

### Ручной backup

```bash
docker compose exec postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > /tmp/manual.sql.gz'
```

### Restore из бэкапа

1. Остановить приложение:

```bash
docker compose stop app
```

2. Скопировать backup в контейнер postgres и восстановить:

```bash
docker compose cp /path/to/backup.sql.gz postgres:/tmp/backup.sql.gz
docker compose exec postgres sh -c 'gunzip -c /tmp/backup.sql.gz | psql -U "$POSTGRES_USER" "$POSTGRES_DB"'
```

3. Запустить приложение:

```bash
docker compose start app
```

## Типовые инциденты

- `health` degraded: проверить доступность `postgres`/`redis`.
- Нет напоминаний: проверить `/digest status`, timezone пользователя и логи `app`.
- Ошибки миграции: проверить `DATABASE_URL` и версию схемы (`alembic current`).
