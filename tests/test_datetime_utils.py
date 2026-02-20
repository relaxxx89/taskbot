from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.utils.datetime_utils import format_dt, parse_due_input


def test_parse_due_input_and_format_roundtrip() -> None:
    utc_dt = parse_due_input("2026-02-20 12:30", "Europe/Moscow")
    assert utc_dt is not None
    assert utc_dt.tzinfo is not None
    assert format_dt(utc_dt, "Europe/Moscow") == "20.02.2026 12:30"


def test_parse_due_natural_today_tomorrow() -> None:
    today = parse_due_input("сегодня", "Europe/Moscow")
    tomorrow = parse_due_input("завтра 09:30", "Europe/Moscow")

    assert today is not None
    assert tomorrow is not None
    assert format_dt(today, "Europe/Moscow").endswith("18:00")
    assert format_dt(tomorrow, "Europe/Moscow").endswith("09:30")


def test_parse_due_relative_and_short_syntax() -> None:
    two_days = parse_due_input("через 2 дня", "Europe/Moscow")
    plus_hours = parse_due_input("+6h", "Europe/Moscow")
    plus_days_ru = parse_due_input("+3д", "Europe/Moscow")

    assert two_days is not None
    assert plus_hours is not None
    assert plus_days_ru is not None


def test_parse_due_none_aliases() -> None:
    assert parse_due_input("-", "Europe/Moscow") is None
    assert parse_due_input("без срока", "Europe/Moscow") is None


def test_parse_due_invalid_phrase() -> None:
    with pytest.raises(ValueError):
        parse_due_input("потом как-нибудь", "Europe/Moscow")
