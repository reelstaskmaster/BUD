from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.types import BufferedInputFile
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import repositories as repo
from app.db.models import Message
from app.services.openai_client import ChatResult

logger = logging.getLogger(__name__)

ProcessBatch = Callable[[int, list[Message]], Awaitable[ChatResult]]
AfterReply = Callable[[int], Awaitable[None]]

TYPING_INTERVAL_S = 4.0
ERROR_REPLY = "Не получилось ответить, попробуй ещё раз."
TELEGRAM_TEXT_LIMIT = 4096


@dataclass
class ChatState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    busy: bool = False
    stop_typing: asyncio.Event = field(default_factory=asyncio.Event)
    typing_task: asyncio.Task[None] | None = None


class ChatCoalescer:
    def __init__(
        self,
        *,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        process_batch: ProcessBatch,
        debounce_s: float,
        after_reply: AfterReply | None = None,
    ) -> None:
        self.bot = bot
        self.session_factory = session_factory
        self.process_batch = process_batch
        self.debounce_s = debounce_s
        self.after_reply = after_reply
        self._states: dict[int, ChatState] = {}

    def _state(self, chat_id: int) -> ChatState:
        state = self._states.get(chat_id)
        if state is None:
            state = ChatState()
            self._states[chat_id] = state
        return state

    async def notify(self, chat_id: int) -> None:
        state = self._state(chat_id)
        async with state.lock:
            self._ensure_typing(chat_id, state)
            if not state.busy:
                state.busy = True
                asyncio.create_task(
                    self._process_loop(chat_id), name=f"coalesce-{chat_id}"
                )

    def _ensure_typing(self, chat_id: int, state: ChatState) -> None:
        if state.typing_task and not state.typing_task.done():
            return
        state.stop_typing = asyncio.Event()
        state.typing_task = asyncio.create_task(
            self._typing_loop(chat_id, state.stop_typing)
        )

    def _stop_typing(self, state: ChatState) -> None:
        state.stop_typing.set()
        task = state.typing_task
        state.typing_task = None
        if task and not task.done():
            task.cancel()

    async def _typing_loop(self, chat_id: int, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self.bot.send_chat_action(chat_id, ChatAction.TYPING)
            except Exception:
                logger.exception("Failed to send typing action to chat %s", chat_id)
            try:
                await asyncio.wait_for(stop.wait(), timeout=TYPING_INTERVAL_S)
            except asyncio.TimeoutError:
                continue

    async def _process_loop(self, chat_id: int) -> None:
        state = self._state(chat_id)
        failed = False
        try:
            await asyncio.sleep(self.debounce_s)
            while True:
                async with self.session_factory() as session:
                    batch = await repo.list_unanswered(session, chat_id)
                if not batch:
                    break
                batch_ids = {message.id for message in batch}
                try:
                    result = await self.process_batch(chat_id, batch)
                except Exception:
                    logger.exception("LLM processing failed for chat %s", chat_id)
                    await self._send_text(chat_id, ERROR_REPLY)
                    failed = True
                    break

                async with self.session_factory() as session:
                    current = await repo.list_unanswered(session, chat_id)
                extra_ids = {message.id for message in current} - batch_ids
                if extra_ids:
                    continue

                await self._send_result(chat_id, result)
                async with self.session_factory() as session:
                    await repo.mark_answered(session, list(batch_ids))
                    await repo.add_message(
                        session,
                        chat_id=chat_id,
                        role="assistant",
                        content=result.text or "",
                        media_type="image_gen" if result.image_bytes else "text",
                        answered=True,
                    )
                    await session.commit()
                if self.after_reply:
                    asyncio.create_task(self.after_reply(chat_id))
                break
        finally:
            async with state.lock:
                state.busy = False
                self._stop_typing(state)
            if not failed:
                async with self.session_factory() as session:
                    leftover = await repo.list_unanswered(session, chat_id)
                if leftover:
                    await self.notify(chat_id)

    async def _send_result(self, chat_id: int, result: ChatResult) -> None:
        text = result.text.strip() if result.text else ""
        if result.image_bytes:
            photo = BufferedInputFile(result.image_bytes, filename="image.png")
            caption = text[:1024] if text else None
            await self.bot.send_photo(chat_id, photo, caption=caption)
            if len(text) > 1024:
                await self._send_text(chat_id, text)
            return
        await self._send_text(chat_id, text or "…")

    async def _send_text(self, chat_id: int, text: str) -> None:
        for start in range(0, max(len(text), 1), TELEGRAM_TEXT_LIMIT):
            chunk = text[start : start + TELEGRAM_TEXT_LIMIT]
            await self.bot.send_message(chat_id, chunk)
