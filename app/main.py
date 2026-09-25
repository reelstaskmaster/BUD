'''Telegram GPT bot with memory and message coalescing.

Setup:
  cp .env.example .env
  docker compose up -d --build
'''

from __future__ import annotations

import asyncio
import logging
import signal

from aiohttp import web
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

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
    )

    # Event to signal graceful shutdown
    stop_event = asyncio.Event()

    def signal_handler():
        # Set the event to trigger shutdown when a signal is received
        stop_event.set()

    loop = asyncio.get_running_loop()
    try:
        # Register signal handlers for graceful shutdown
        loop.add_signal_handler(signal.SIGINT, signal_handler)
        loop.add_signal_handler(signal.SIGTERM, signal_handler)
    except NotImplementedError:
        # Signal handling may not be supported on all platforms (e.g., Windows)
        pass

    try:
        await coalescer.recover_pending()

        if settings.bot_mode.lower() == "webhook":
            if not settings.webhook_base_url:
                raise RuntimeError("WEBHOOK_BASE_URL is required in webhook mode")
            if not settings.webhook_secret:
                raise RuntimeError("WEBHOOK_SECRET is required in webhook mode")

            webhook_url = (
                f"{settings.webhook_base_url.rstrip('/')}{settings.webhook_path}"
            )
            app = web.Application()
            app.router.add_get("/health", lambda request: web.Response(text="ok"))
            webhook_handler = SimpleRequestHandler(
                dispatcher=dp,
                bot=bot,
                secret_token=settings.webhook_secret,
                handle_in_background=True,
            )
            webhook_handler.register(app, path=settings.webhook_path)
            setup_application(app, dp, bot=bot)

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host="0.0.0.0", port=settings.port)
            await site.start()
            try:
                await bot.set_webhook(
                    webhook_url,
                    secret_token=settings.webhook_secret,
                )
                logger.info("Starting webhook on %s", webhook_url)
                # Wait for stop event instead of a permanent block
                await stop_event.wait()
            finally:
                await runner.cleanup()
        else:
            await bot.delete_webhook(drop_pending_updates=False)
            logger.info("Starting polling")
            await dp.start_polling(bot)
    finally:
        # Cleanup resources on exit
        await coalescer.shutdown()
        await bot.session.close()
        await engine.dispose()
def main() -> None:
    asyncio.run(run())
if __name__ == "__main__":
    main()