from __future__ import annotations

import asyncio
import logging

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from redis.asyncio import Redis

from app.api import create_api_app
from app.bot.commands import setup_bot_commands
from app.bot.handlers import build_router
from app.config import get_settings
from app.db.session import dispose_engine, get_session_factory, init_engine
from app.logging_config import configure_logging
from app.services.scheduler_service import process_digest, process_reminders

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.LOG_LEVEL)

    init_engine(settings.DATABASE_URL)
    session_factory = get_session_factory()

    redis_client = Redis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    storage = RedisStorage(redis=redis_client)

    bot = Bot(token=settings.BOT_TOKEN)
    dispatcher = Dispatcher(storage=storage)
    router = build_router(settings, session_factory)
    dispatcher.include_router(router)

    await setup_bot_commands(bot)

    digest_hour, digest_minute = settings.digest_hour_minute
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        process_reminders,
        trigger="interval",
        minutes=1,
        kwargs={"session_factory": session_factory, "bot": bot},
        id="reminders",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        process_digest,
        trigger="interval",
        minutes=1,
        kwargs={
            "session_factory": session_factory,
            "bot": bot,
            "digest_hour": digest_hour,
            "digest_minute": digest_minute,
        },
        id="digest",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()

    api_app = create_api_app(session_factory, redis_client)
    uvicorn_config = uvicorn.Config(
        app=api_app,
        host=settings.HEALTH_HOST,
        port=settings.HEALTH_PORT,
        log_level=settings.LOG_LEVEL.lower(),
    )
    api_server = uvicorn.Server(uvicorn_config)

    polling_task = asyncio.create_task(dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types()))
    api_task = asyncio.create_task(api_server.serve())

    try:
        done, pending = await asyncio.wait({polling_task, api_task}, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            exc = task.exception()
            if exc:
                raise exc
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
        scheduler.shutdown(wait=False)
        await dispatcher.storage.close()
        await bot.session.close()
        await redis_client.close()
        await dispose_engine()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Shutting down TaskBot")
