from __future__ import annotations

import re
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


def _parse_hhmm(raw: str) -> tuple[int, int]:
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError("bad time")
    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("bad time")
    return hour, minute


def parse_due_natural_ru(raw: str, timezone_name: str, now: datetime | None = None) -> datetime | None:
    value = raw.strip().lower()
    if value in {"", "-", "none", "нет", "skip", "без срока"}:
        return None

    local_tz = ZoneInfo(timezone_name)
    local_now = (now or utcnow()).astimezone(local_tz)

    keyword_match = re.fullmatch(r"(сегодня|завтра|послезавтра)(?:\s+(\d{1,2}:\d{2}))?", value)
    if keyword_match:
        keyword = keyword_match.group(1)
        raw_time = keyword_match.group(2)

        day_shift = {"сегодня": 0, "завтра": 1, "послезавтра": 2}[keyword]
        base_date = (local_now + timedelta(days=day_shift)).date()

        if raw_time:
            hour, minute = _parse_hhmm(raw_time)
        elif keyword == "сегодня":
            hour, minute = 18, 0
        else:
            hour, minute = 10, 0

        local_dt = datetime.combine(base_date, time(hour, minute), tzinfo=local_tz)
        return local_dt.astimezone(UTC)

    relative_match = re.fullmatch(r"через\s+(\d+)\s+(день|дня|дней|дн|час|часа|часов|ч)", value)
    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2)
        if unit in {"день", "дня", "дней", "дн"}:
            target_date = (local_now + timedelta(days=amount)).date()
            local_dt = datetime.combine(target_date, time(10, 0), tzinfo=local_tz)
            return local_dt.astimezone(UTC)
        local_dt = local_now + timedelta(hours=amount)
        return local_dt.astimezone(UTC)

    short_match = re.fullmatch(r"\+(\d+)\s*([dDhHдДчЧ])", value)
    if short_match:
        amount = int(short_match.group(1))
        unit = short_match.group(2).lower()
        if unit in {"d", "д"}:
            target_date = (local_now + timedelta(days=amount)).date()
            local_dt = datetime.combine(target_date, time(10, 0), tzinfo=local_tz)
            return local_dt.astimezone(UTC)
        local_dt = local_now + timedelta(hours=amount)
        return local_dt.astimezone(UTC)

    return None


def parse_due_input(raw: str, timezone_name: str) -> datetime | None:
    value = raw.strip()
    natural = parse_due_natural_ru(value, timezone_name)
    if natural is not None:
        return natural
    if value.strip().lower() in {"", "-", "none", "нет", "skip", "без срока"}:
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

    raise ValueError('Примеры: "завтра 10:00", "через 2 дня", "+3d", "2026-03-01 14:30"')


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
