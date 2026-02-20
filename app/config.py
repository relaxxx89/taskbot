from __future__ import annotations

from functools import lru_cache
from typing import Set

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    BOT_TOKEN: str
    ALLOWED_TELEGRAM_IDS: str = Field(default="")
    DATABASE_URL: str = Field(default="postgresql+asyncpg://taskbot:taskbot@postgres:5432/taskbot")
    REDIS_URL: str = Field(default="redis://redis:6379/0")
    TZ_DEFAULT: str = Field(default="UTC")
    DIGEST_TIME: str = Field(default="09:00")
    LOG_LEVEL: str = Field(default="INFO")
    HEALTH_HOST: str = Field(default="0.0.0.0")
    HEALTH_PORT: int = Field(default=8080)
    BACKUP_RETENTION_DAYS: int = Field(default=14)

    @property
    def allowed_telegram_ids(self) -> Set[int]:
        ids: Set[int] = set()
        for item in self.ALLOWED_TELEGRAM_IDS.split(","):
            item = item.strip()
            if not item:
                continue
            ids.add(int(item))
        return ids

    @property
    def digest_hour_minute(self) -> tuple[int, int]:
        raw = self.DIGEST_TIME.strip()
        parts = raw.split(":")
        if len(parts) != 2:
            raise ValueError("DIGEST_TIME must be HH:MM")
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("DIGEST_TIME must be in HH:MM 24h format")
        return hour, minute


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
