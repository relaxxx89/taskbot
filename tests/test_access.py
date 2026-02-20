from __future__ import annotations

from app.bot.middlewares.auth import is_user_allowed


def test_whitelist_access_check() -> None:
    allowed = {1001, 1002}
    assert is_user_allowed(1001, allowed)
    assert not is_user_allowed(2001, allowed)
