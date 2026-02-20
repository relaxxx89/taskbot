from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


_PARSE_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def parse_due_input(raw: str, timezone_name: str) -> datetime | None:
    value = raw.strip()
    if value in {"", "-", "none", "нет", "skip"}:
        return None

    local_tz = ZoneInfo(timezone_name)
    for fmt in _PARSE_FORMATS:
        try:
            parsed = datetime.strptime(value, fmt)
            if fmt.endswith("%H:%M"):
                local_dt = parsed.replace(tzinfo=local_tz)
            else:
                local_dt = datetime.combine(parsed.date(), time(18, 0), tzinfo=local_tz)
            return local_dt.astimezone(UTC)
        except ValueError:
            continue
    raise ValueError("Неверный формат даты. Используйте YYYY-MM-DD HH:MM или DD.MM.YYYY HH:MM")


def format_dt(value: datetime | None, timezone_name: str) -> str:
    if value is None:
        return "—"
    return value.astimezone(ZoneInfo(timezone_name)).strftime("%d.%m.%Y %H:%M")


def local_day_bounds_utc(timezone_name: str, target_date: date | None = None) -> tuple[datetime, datetime]:
    local_tz = ZoneInfo(timezone_name)
    today = target_date or datetime.now(local_tz).date()
    start_local = datetime.combine(today, time.min, tzinfo=local_tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def next_reminder_at(due_at: datetime | None, now_utc: datetime | None = None) -> datetime | None:
    if due_at is None:
        return None
    now = now_utc or utcnow()
    preferred = due_at - timedelta(hours=1)
    if preferred > now:
        return preferred
    return due_at
