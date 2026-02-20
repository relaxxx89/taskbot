from __future__ import annotations

from app.utils.datetime_utils import format_dt, parse_due_input


def test_parse_due_input_and_format_roundtrip() -> None:
    utc_dt = parse_due_input("2026-02-20 12:30", "Europe/Moscow")
    assert utc_dt is not None
    assert utc_dt.tzinfo is not None
    assert format_dt(utc_dt, "Europe/Moscow") == "20.02.2026 12:30"
