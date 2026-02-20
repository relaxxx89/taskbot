from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def create_api_app(session_factory: async_sessionmaker[AsyncSession], redis_client: Redis) -> FastAPI:
    app = FastAPI(title="TaskBot API", version="1.0.0")

    @app.get("/health")
    async def health() -> JSONResponse:
        payload: dict[str, Any] = {"status": "ok", "checks": {}}
        status_code = 200

        try:
            async with session_factory() as session:
                await session.execute(text("SELECT 1"))
            payload["checks"]["database"] = "ok"
        except Exception as exc:
            payload["checks"]["database"] = f"error: {exc.__class__.__name__}"
            status_code = 503

        try:
            await redis_client.ping()
            payload["checks"]["redis"] = "ok"
        except Exception as exc:
            payload["checks"]["redis"] = f"error: {exc.__class__.__name__}"
            status_code = 503

        if status_code != 200:
            payload["status"] = "degraded"

        return JSONResponse(content=payload, status_code=status_code)

    return app
