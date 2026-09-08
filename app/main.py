"""Telegram GPT bot with memory and message coalescing.

Setup:
  cp .env.example .env
  docker compose up -d --build
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from app.bot import build_dispatcher
from app.config import get_settings
from app.db.session import create_engine_and_session
from app.services.coalescer import ChatCoalescer
from app.services.memory import MemoryService
from app.services.openai_client import OpenAIService
from app.services.pipeline import ReplyPipeline

logger = logging.getLogger(__name__)


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings.database_url)

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(),
    )
    openai = OpenAIService(settings)
    memory = MemoryService(session_factory, openai, settings)
    pipeline = ReplyPipeline(
        bot=bot,
        session_factory=session_factory,
        openai=openai,
        memory=memory,
        settings=settings,
    )
    coalescer = ChatCoalescer(
        bot=bot,
        session_factory=session_factory,
        process_batch=pipeline.process_batch,
        debounce_s=settings.coalesce_debounce_s,
        after_reply=memory.maintain,
    )

    dp = build_dispatcher(
        bot=bot,
        session_factory=session_factory,
        coalescer=coalescer,
        openai=openai,
        settings=settings,
    )

    try:
        logger.info("Starting polling")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
