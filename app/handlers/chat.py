from __future__ import annotations

import logging
from io import BytesIO

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction, ChatType
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import repositories as repo
from app.services.coalescer import ChatCoalescer
from app.services.openai_client import OpenAIService

logger = logging.getLogger(__name__)

private = F.chat.type == ChatType.PRIVATE


def build_router(
    *,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
    coalescer: ChatCoalescer,
    openai: OpenAIService,
) -> Router:
    router = Router(name="chat")

    @router.message(CommandStart(), private)
    async def on_start(message: Message) -> None:
        async with session_factory() as session:
            profile = await repo.get_profile(session, message.chat.id)
            await session.commit()
        if not profile.onboarding_complete:
            return
        await message.answer(
            "Привет. Пиши текстом, голосом или кидай картинку — я отвечу.\n"
            "Могу запоминать факты и рисовать по просьбе.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings:open")],
            ]),
        )

    @router.message(private, F.text, ~F.text.startswith("/"))
    async def on_text(message: Message) -> None:
        text = (message.text or "").strip()
        if not text:
            return
        async with session_factory() as session:
            profile = await repo.get_profile(session, message.chat.id)
            if not profile.onboarding_complete and profile.onboarding_step == 6:
                profile.about = text
                profile.onboarding_complete = True
                profile.onboarding_step = 7
                await session.commit()
                await message.answer(
                    "Готово. 🧠 Я настроил базовый профиль BUD под тебя.\n\n"
                    "Первые 3 дня полная долгосрочная память работает бесплатно. "
                    "Дальше сохранённая память не удалится — она просто заморозится, пока ты не продлишь доступ.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings:open")],
                    ]),
                )
                return
            await repo.add_message(
                session,
                chat_id=message.chat.id,
                role="user",
                content=text,
                media_type="text",
            )
            await session.commit()
        await coalescer.notify(message.chat.id)

    @router.message(private, F.voice | F.audio | F.video_note)
    async def on_voice(message: Message) -> None:
        attachment = message.voice or message.audio or message.video_note
        if attachment is None:
            return
        await _ingest_audio(
            bot=bot,
            openai=openai,
            session_factory=session_factory,
            coalescer=coalescer,
            message=message,
            file_id=attachment.file_id,
            filename=_audio_filename(message),
        )

    @router.message(private, F.photo)
    async def on_photo(message: Message) -> None:
        if not message.photo:
            return
        photo = message.photo[-1]
        caption = (message.caption or "").strip()
        async with session_factory() as session:
            await repo.add_message(
                session,
                chat_id=message.chat.id,
                role="user",
                content=caption,
                media_type="photo",
                telegram_file_id=photo.file_id,
            )
            await session.commit()
        await coalescer.notify(message.chat.id)

    @router.message(private, F.document)
    async def on_document(message: Message) -> None:
        document = message.document
        if document is None:
            return
        mime = (document.mime_type or "").lower()
        if mime.startswith("audio/") or mime in {"video/mp4", "application/ogg"}:
            filename = document.file_name or "audio.ogg"
            await _ingest_audio(
                bot=bot,
                openai=openai,
                session_factory=session_factory,
                coalescer=coalescer,
                message=message,
                file_id=document.file_id,
                filename=filename,
            )
            return
        if not mime.startswith("image/"):
            return
        caption = (message.caption or "").strip()
        async with session_factory() as session:
            await repo.add_message(
                session,
                chat_id=message.chat.id,
                role="user",
                content=caption,
                media_type="photo",
                telegram_file_id=document.file_id,
            )
            await session.commit()
        await coalescer.notify(message.chat.id)

    return router


async def _ingest_audio(
    *,
    bot: Bot,
    openai: OpenAIService,
    session_factory: async_sessionmaker[AsyncSession],
    coalescer: ChatCoalescer,
    message: Message,
    file_id: str,
    filename: str,
) -> None:
    await bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    try:
        audio = await _download(bot, file_id)
        text = await openai.transcribe(audio, filename=filename)
    except Exception:
        logger.exception("Voice transcription failed")
        await message.answer("Не получилось разобрать голосовое, попробуй ещё раз.")
        return
    if not text:
        await message.answer("Пустая расшифровка, отправь ещё раз.")
        return
    logger.info("Transcribed voice for chat %s: %s", message.chat.id, text[:200])
    caption = (message.caption or "").strip()
    content = f"{caption}\n{text}".strip() if caption else text
    async with session_factory() as session:
        await repo.add_message(
            session,
            chat_id=message.chat.id,
            role="user",
            content=content,
            media_type="voice",
        )
        await session.commit()
    await coalescer.notify(message.chat.id)


def _audio_filename(message: Message) -> str:
    if message.video_note:
        return "video_note.mp4"
    if message.audio:
        name = message.audio.file_name or "audio.mp3"
        return name if "." in name else f"{name}.mp3"
    return "voice.ogg"


async def _download(bot: Bot, file_id: str) -> bytes:
    file = await bot.get_file(file_id)
    if not file.file_path:
        raise RuntimeError(f"Telegram file path missing for {file_id}")
    stream = BytesIO()
    await bot.download_file(file.file_path, destination=stream)
    data = stream.getvalue()
    if not data:
        raise RuntimeError(f"Downloaded empty file for {file_id}")
    return data
