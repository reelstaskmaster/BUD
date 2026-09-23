from __future__ import annotations

import mimetypes
from io import BytesIO

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db import repositories as repo
from app.db.models import Message
from app.services.agent_loop import AgentLoop
from app.services.memory import MemoryService
from app.services.openai_client import ChatResult, OpenAIInputMessage, OpenAIService
from app.services.prompt import build_instructions


class ReplyPipeline:
    def __init__(
        self,
        *,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        openai: OpenAIService,
        memory: MemoryService,
        settings: Settings,
    ) -> None:
        self.bot = bot
        self.session_factory = session_factory
        self.openai = openai
        self.memory = memory
        self.settings = settings
        self.agent_loop = AgentLoop()

    async def process_batch(self, chat_id: int, batch: list[Message]) -> ChatResult:
        query = "\n".join(message.content for message in batch if message.content)
        memory = await self.memory.retrieve(chat_id, query)
        instructions = build_instructions(memory, query=query)

        async with self.session_factory() as session:
            recent = await repo.list_recent_messages(
                session, chat_id, self.settings.recent_messages
            )

        openai_messages: list[OpenAIInputMessage] = []
        for message in recent:
            image_bytes = None
            image_mime_type = None
            if message.media_type == "photo" and message.telegram_file_id:
                image_bytes, image_mime_type = await self._download_file(message.telegram_file_id)
            resolved_mime_type = (
                message.media_mime_type or image_mime_type if image_bytes else None
            )
            openai_messages.append(
                OpenAIInputMessage(
                    role=message.role,
                    text=_message_text_for_llm(message),
                    image_bytes=image_bytes,
                    image_mime_type=resolved_mime_type,
                )
            )

        async with self.session_factory() as session:

            async def handle_tool(name: str, args: dict) -> str:
                return await self.memory.tool_handler(session, chat_id, name, args)

            async def execute(runtime_instructions: str) -> ChatResult:
                return await self.openai.chat(
                    instructions=runtime_instructions,
                    messages=openai_messages,
                    tool_handler=handle_tool,
                )

            return await self.agent_loop.run(
                query=query,
                instructions=instructions,
                executor=execute,
            )

    async def _download_file(self, file_id: str) -> tuple[bytes, str | None]:
        file = await self.bot.get_file(file_id)
        if not file.file_path:
            raise RuntimeError(f"Telegram file path missing for {file_id}")
        stream = BytesIO()
        await self.bot.download_file(file.file_path, destination=stream)
        data = stream.getvalue()
        if not data:
            raise RuntimeError(f"Downloaded empty file for {file_id}")
        mime_type, _ = mimetypes.guess_type(file.file_path)
        return data, mime_type


def _message_text_for_llm(message: Message) -> str:
    text = message.content or ""
    if message.role == "user" and message.media_type == "voice":
        return (
            "The user sent a voice/audio message. This is the transcription of "
            "what they said — answer it as their message:\n"
            f"{text}"
        )
    return text
