from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.enums import ChatType
from aiogram.types import TelegramObject, Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.handlers.chat import build_router as build_chat_router
from app.handlers.onboarding import build_router as build_onboarding_router
from app.handlers.payments import build_router as build_payments_router
from app.handlers.settings import build_router as build_settings_router
from app.services.coalescer import ChatCoalescer
from app.services.openai_client import OpenAIService
from app.config import Settings


class PrivateOnlyMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat = getattr(event, "chat", None)
        if chat is None and isinstance(event, Update):
            incoming = event.message or event.edited_message or event.callback_query
            chat = incoming.message.chat if getattr(incoming, "message", None) else getattr(incoming, "chat", None)
        if chat is not None and chat.type != ChatType.PRIVATE:
            return None
        return await handler(event, data)


def build_dispatcher(
    *,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    coalescer: ChatCoalescer,
    openai: OpenAIService,
    settings: Settings,
) -> Dispatcher:
    dp = Dispatcher()
    dp.message.middleware(PrivateOnlyMiddleware())
    dp.callback_query.middleware(PrivateOnlyMiddleware())
    dp.include_router(build_onboarding_router(session_factory=session_factory))
    dp.include_router(build_settings_router(session_factory=session_factory))
    dp.include_router(build_payments_router(session_factory=session_factory, settings=settings))
    dp.include_router(
        build_chat_router(
            bot=bot,
            session_factory=session_factory,
            coalescer=coalescer,
            openai=openai,
        )
    )
    return dp
