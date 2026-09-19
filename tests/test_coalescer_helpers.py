import pytest

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
