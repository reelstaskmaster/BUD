from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.enums import ChatType
from aiogram.types import TelegramObject, Update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.handlers.chat import build_router
from app.services.coalescer import ChatCoalescer
from app.services.openai_client import OpenAIService


class PrivateOnlyMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat = getattr(event, "chat", None)
        if chat is None and isinstance(event, Update):
            incoming = event.message or event.edited_message
            chat = incoming.chat if incoming else None
        if chat is not None and chat.type != ChatType.PRIVATE:
            return None
        return await handler(event, data)


def build_dispatcher(
    *,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    coalescer: ChatCoalescer,
    openai: OpenAIService,
) -> Dispatcher:
    dp = Dispatcher()
    dp.message.middleware(PrivateOnlyMiddleware())
    dp.include_router(
        build_router(
            bot=bot,
            session_factory=session_factory,
            coalescer=coalescer,
            openai=openai,
        )
    )
    return dp
