import asyncio

import pytest

from app.db import repositories as repo

from app.services.coalescer import ChatCoalescer, ChatResult, TELEGRAM_TEXT_LIMIT


class FakeBot:
    def __init__(self) -> None:
        self.messages = []
        self.photos = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))

    async def send_photo(self, chat_id: int, photo, caption=None) -> None:
        self.photos.append((chat_id, photo, caption))


def make_coalescer(bot: FakeBot) -> ChatCoalescer:
    return ChatCoalescer(
        bot=bot,  # type: ignore[arg-type]
        session_factory=None,  # type: ignore[arg-type]
        process_batch=None,  # type: ignore[arg-type]
        debounce_s=0,
    )


@pytest.mark.asyncio
async def test_send_text_splits_at_telegram_limit() -> None:
    bot = FakeBot()
    coalescer = make_coalescer(bot)
    text = "x" * (TELEGRAM_TEXT_LIMIT + 5)

    await coalescer._send_text(123, text)

    assert [len(chunk) for _, chunk in bot.messages] == [TELEGRAM_TEXT_LIMIT, 5]
    assert "".join(chunk for _, chunk in bot.messages) == text


@pytest.mark.asyncio
async def test_send_text_skips_empty_text() -> None:
    bot = FakeBot()
    coalescer = make_coalescer(bot)

    await coalescer._send_text(123, "")

    assert bot.messages == []


@pytest.mark.asyncio
async def test_send_result_sends_image_and_truncates_long_caption() -> None:
    bot = FakeBot()
    coalescer = make_coalescer(bot)
    text = "a" * 1025

    await coalescer._send_result(123, ChatResult(text=text, image_bytes=b"image"))

    assert len(bot.photos) == 1
    assert bot.photos[0][0] == 123
    assert bot.photos[0][2] == "a" * 1024
    assert bot.messages == [(123, "a")]


@pytest.mark.asyncio
async def test_send_result_uses_placeholder_for_empty_text() -> None:
    bot = FakeBot()
    coalescer = make_coalescer(bot)

    await coalescer._send_result(123, ChatResult(text=""))

    assert bot.messages == [(123, "…")]


@pytest.mark.asyncio
async def test_send_result_image_caption_is_not_duplicated_after_1024() -> None:
    bot = FakeBot()
    coalescer = make_coalescer(bot)
    text = "a" * 1024

    await coalescer._send_result(123, ChatResult(text=text, image_bytes=b"image"))

    assert bot.photos[0][2] == text
    assert bot.messages == []


@pytest.mark.asyncio
async def test_after_reply_failure_is_observed_and_does_not_escape() -> None:
    bot = FakeBot()

    async def after_reply(chat_id):
        raise RuntimeError("maintenance failed")

    coalescer = ChatCoalescer(
        bot=bot,
        session_factory=None,
        process_batch=None,
        debounce_s=0,
        after_reply=after_reply,
    )
    task = asyncio.create_task(after_reply(123))
    await asyncio.sleep(0)
    coalescer._log_background_failure(task)
    assert task.done()


@pytest.mark.asyncio
async def test_send_error_reply_survives_telegram_failure() -> None:
    class BrokenBot(FakeBot):
        async def send_message(self, chat_id: int, text: str) -> None:
            raise RuntimeError("telegram unavailable")

    coalescer = make_coalescer(BrokenBot())

    await coalescer._send_error_reply(123)


@pytest.mark.asyncio
async def test_send_result_does_not_mark_delivery_before_telegram_send() -> None:
    bot = FakeBot()
    coalescer = make_coalescer(bot)
    result = ChatResult(text="hello", image_bytes=None)

    await coalescer._send_result(42, result)

    assert bot.messages == [(42, "hello")]


def test_chat_coalescer_has_unique_process_owner() -> None:
    first = make_coalescer(FakeBot())
    second = make_coalescer(FakeBot())

    assert first._owner
    assert second._owner
    assert first._owner != second._owner


@pytest.mark.asyncio
async def test_lease_heartbeat_sets_loss_event() -> None:
    bot = FakeBot()

    class SessionContext:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def commit(self):
            return None

    class SessionFactory:
        def __call__(self):
            return SessionContext()

    coalescer = ChatCoalescer(
        bot=bot,
        session_factory=SessionFactory(),  # type: ignore[arg-type]
        process_batch=None,  # type: ignore[arg-type]
        debounce_s=0,
    )

    original = repo.renew_chat_processing
    try:
        async def lost(session, chat_id, owner):
            return False

        repo.renew_chat_processing = lost
        event = asyncio.Event()
        task = asyncio.create_task(coalescer._lease_heartbeat(123, event))
        await asyncio.sleep(0)
        assert event.is_set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    finally:
        repo.renew_chat_processing = original


@pytest.mark.asyncio
async def test_delivery_retry_worker_survives_transient_error(monkeypatch) -> None:
    bot = FakeBot()
    coalescer = make_coalescer(bot)
    calls = 0

    original = repo.list_pending_reply_chat_ids
    monkeypatch.setattr("app.services.coalescer.DELIVERY_RETRY_INTERVAL_S", 0)

    async def flaky(session, limit=1000):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("temporary db failure")
        return []

    repo.list_pending_reply_chat_ids = flaky
    try:
        task = asyncio.create_task(coalescer._delivery_retry_loop())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert calls >= 2
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    finally:
        repo.list_pending_reply_chat_ids = original

