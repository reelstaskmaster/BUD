from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.types import BufferedInputFile
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import repositories as repo
from app.db.models import Message
from app.services.openai_client import ChatResult
from app.db.models import ReplyDelivery

logger = logging.getLogger(__name__)

ProcessBatch = Callable[[int, list[Message]], Awaitable[ChatResult]]
AfterReply = Callable[[int], Awaitable[None]]

TYPING_INTERVAL_S = 4.0
LEASE_RENEW_INTERVAL_S = 60.0
DELIVERY_RETRY_INTERVAL_S = 30.0
ERROR_REPLY = "Не получилось ответить, попробуй ещё раз."
TELEGRAM_TEXT_LIMIT = 4096


@dataclass
class ChatState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    busy: bool = False
    stop_typing: asyncio.Event = field(default_factory=asyncio.Event)
    typing_task: asyncio.Task[None] | None = None
    process_task: asyncio.Task[None] | None = None


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
        self._owner = uuid.uuid4().hex
        self._retry_task: asyncio.Task[None] | None = None

    def _state(self, chat_id: int) -> ChatState:
        state = self._states.get(chat_id)
        if state is None:
            state = ChatState()
            self._states[chat_id] = state
        return state

    async def shutdown(self) -> None:
        if self._retry_task and not self._retry_task.done():
            self._retry_task.cancel()
            await asyncio.gather(self._retry_task, return_exceptions=True)
        self._retry_task = None
        states = list(self._states.values())
        tasks: list[asyncio.Task[None]] = []
        for state in states:
            for task in (state.process_task, state.typing_task):
                if task and not task.done():
                    task.cancel()
                    tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._states.clear()

    async def recover_pending(self) -> None:
        self._ensure_retry_worker()
        async with self.session_factory() as session:
            chat_ids = await repo.list_pending_reply_chat_ids(session)
        for chat_id in chat_ids:
            await self.notify(chat_id)

    def _ensure_retry_worker(self) -> None:
        if self._retry_task and not self._retry_task.done():
            return
        self._retry_task = asyncio.create_task(
            self._delivery_retry_loop(), name="reply-delivery-retry"
        )
        self._retry_task.add_done_callback(self._log_background_failure)

    async def _delivery_retry_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(DELIVERY_RETRY_INTERVAL_S)
                async with self.session_factory() as session:
                    chat_ids = await repo.list_pending_reply_chat_ids(session)
                for chat_id in chat_ids:
                    await self.notify(chat_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reply delivery retry worker failed")

    async def notify(self, chat_id: int) -> None:
        self._ensure_retry_worker()
        state = self._state(chat_id)
        async with state.lock:
            self._ensure_typing(chat_id, state)
            if not state.busy:
                state.busy = True
                state.process_task = asyncio.create_task(
                    self._process_loop(chat_id), name=f"coalesce-{chat_id}"
                )
                state.process_task.add_done_callback(self._log_background_failure)

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

    async def _deliver_pending(self, delivery: ReplyDelivery) -> bool:
        try:
            result = ChatResult(
                text=delivery.content,
                image_bytes=delivery.image_bytes,
            )
            await self._send_result(delivery.chat_id, result)
        except Exception as exc:
            logger.exception("Failed to deliver reply delivery %s", delivery.id)
            async with self.session_factory() as session:
                await repo.mark_reply_delivery_attempt(session, delivery.id, repr(exc))
                await session.commit()
            return False
        async with self.session_factory() as session:
            marked = await repo.mark_reply_delivery_sent(session, delivery.id)
            await session.commit()
        return marked

    async def _process_loop(self, chat_id: int) -> None:
        state = self._state(chat_id)
        failed = False
        claimed = False
        lease_held = False
        try:
            await asyncio.sleep(self.debounce_s)
            async with self.session_factory() as session:
                claimed = await repo.claim_chat_processing(
                    session, chat_id, self._owner
                )
                lease_held = claimed
                await session.commit()
            if not claimed:
                return
            async with self.session_factory() as session:
                pending = await repo.list_pending_reply_deliveries(session, chat_id, limit=10)
            if pending:
                for delivery in pending:
                    if lease_lost.is_set():
                    logger.warning("Aborting delivery for chat %s after lease loss", chat_id)
                    failed = True
                    break
                if not await self._deliver_pending(delivery):
                        failed = True
                        return
            while True:
                async with self.session_factory() as session:
                    claimed = await repo.claim_chat_processing(
                        session, chat_id, self._owner
                    )
                    if claimed:
                        lease_held = True
                        batch = await repo.list_unanswered(session, chat_id)
                    else:
                        batch = []
                    await session.commit()
                if not claimed:
                    return
                if not batch:
                    break
                batch_ids = {message.id for message in batch}
                lease_lost = asyncio.Event()
                lease_task = asyncio.create_task(
                    self._lease_heartbeat(chat_id, lease_lost),
                    name=f"lease-heartbeat-{chat_id}",
                )
                try:
                    result = await self.process_batch(chat_id, batch)
                except Exception:
                    logger.exception("LLM processing failed for chat %s", chat_id)
                    await self._send_error_reply(chat_id)
                    failed = True
                    break
                finally:
                    lease_task.cancel()
                    await asyncio.gather(lease_task, return_exceptions=True)

                if lease_lost.is_set():
                    logger.warning("Aborting reply for chat %s after lease loss", chat_id)
                    failed = True
                    break

                async with self.session_factory() as session:
                    current = await repo.list_unanswered(session, chat_id)
                extra_ids = {message.id for message in current} - batch_ids
                if extra_ids:
                    continue

                try:
                    async with self.session_factory() as session:
                        if not await repo.renew_chat_processing(session, chat_id, self._owner):
                            logger.warning("Lease lost before persisting reply for chat %s", chat_id)
                            failed = True
                            break
                        await repo.mark_answered(session, list(batch_ids))
                        await repo.add_message(
                            session,
                            chat_id=chat_id,
                            role="assistant",
                            content=result.text or "",
                            media_type="image_gen" if result.image_bytes else "text",
                            answered=True,
                        )
                        delivery = await repo.create_reply_delivery(
                            session,
                            chat_id=chat_id,
                            source_message_ids=list(batch_ids),
                            content=result.text or "",
                            media_type="image_gen" if result.image_bytes else "text",
                            image_bytes=result.image_bytes,
                        )
                        await session.commit()
                except Exception:
                    logger.exception("Failed to persist reply delivery for chat %s", chat_id)
                    failed = True
                    break

                if not await self._deliver_pending(delivery):
                    failed = True
                    break

                if self.after_reply:
                    task = asyncio.create_task(
                        self.after_reply(chat_id), name=f"after-reply-{chat_id}"
                    )
                    task.add_done_callback(self._log_background_failure)
                break
        finally:
            if lease_held:
                try:
                    async with self.session_factory() as session:
                        await repo.release_chat_processing(
                            session, chat_id, self._owner
                        )
                        await session.commit()
                except Exception:
                    logger.exception(
                        "Failed to release processing lease for chat %s", chat_id
                    )
            async with state.lock:
                state.busy = False
                state.process_task = None
                self._stop_typing(state)
            if not failed:
                try:
                    async with self.session_factory() as session:
                        leftover = await repo.list_unanswered(session, chat_id)
                except Exception:
                    logger.exception(
                        "Failed to inspect leftover messages for chat %s", chat_id
                    )
                    leftover = []
                if leftover:
                    await self.notify(chat_id)

    async def _lease_heartbeat(self, chat_id: int, lease_lost: asyncio.Event) -> None:
        try:
            while True:
                await asyncio.sleep(LEASE_RENEW_INTERVAL_S)
                async with self.session_factory() as session:
                    renewed = await repo.renew_chat_processing(
                        session, chat_id, self._owner
                    )
                    await session.commit()
                if not renewed:
                    logger.warning("Chat processing lease lost for chat %s", chat_id)
                    lease_lost.set()
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Chat processing lease heartbeat failed for chat %s", chat_id)

    async def _recover_delivery_loop(self, chat_id: int) -> None:
        async with self.session_factory() as session:
            pending = await repo.list_pending_reply_deliveries(session, chat_id, limit=10)
        for delivery in pending:
            if not await self._deliver_pending(delivery):
                return

    async def _send_error_reply(self, chat_id: int) -> None:
        try:
            await self._send_text(chat_id, ERROR_REPLY)
        except Exception:
            logger.exception("Failed to send error reply to chat %s", chat_id)

    @staticmethod
    def _log_background_failure(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            logger.exception("Background after-reply task failed")

    async def _send_result(self, chat_id: int, result: ChatResult) -> None:
        text = result.text.strip() if result.text else ""
        if result.image_bytes:
            photo = BufferedInputFile(result.image_bytes, filename="image.png")
            caption = text[:1024] if text else None
            await self.bot.send_photo(chat_id, photo, caption=caption)
            if len(text) > 1024:
                await self._send_text(chat_id, text[1024:])
            return
        await self._send_text(chat_id, text or "…")

    async def _send_text(self, chat_id: int, text: str) -> None:
        if not text:
            return
        for start in range(0, len(text), TELEGRAM_TEXT_LIMIT):
            chunk = text[start : start + TELEGRAM_TEXT_LIMIT]
            await self.bot.send_message(chat_id, chunk)
