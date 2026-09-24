from __future__ import annotations

import mimetypes
import re
from io import BytesIO

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db import repositories as repo
from app.db.models import Message
from app.services.agent_loop import AgentLoop
from app.services.context_manager import ContextManager
from app.services.memory import MemoryService
from app.services.openai_client import ChatResult, OpenAIInputMessage, OpenAIService
from app.services.prompt import build_instructions
from app.services.capability_executor import CapabilityExecutor
from app.services.capability_registry import Capability, CapabilityRegistry, RiskLevel
from app.services.runtime_capabilities import RuntimeCapabilities


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
        self.context_manager = ContextManager(settings.context_max_chars)
        self.capabilities = CapabilityRegistry()
        self.capability_executor = CapabilityExecutor(self.capabilities)
        runtime = RuntimeCapabilities(settings)
        self.capabilities.register(Capability("github_read_file", "Read a text file from GitHub. Read-only.", RiskLevel.READ, runtime.github_read_file))
        self.capabilities.register(Capability("github_create_branch", "Create a GitHub branch from a base ref.", RiskLevel.WRITE, runtime.github_create_branch))
        self.capabilities.register(Capability("github_update_file", "Create or update a GitHub text file on a branch.", RiskLevel.WRITE, runtime.github_update_file))
        self.capabilities.register(Capability("github_create_pr", "Create a draft GitHub pull request. Never merges it.", RiskLevel.WRITE, runtime.github_create_pr))
        self.capabilities.register(Capability("railway_health", "Check the BUD/Railway HTTP health endpoint. Read-only.", RiskLevel.READ, runtime.railway_health))

    async def process_batch(self, chat_id: int, batch: list[Message]) -> ChatResult:
        query = "\n".join(message.content for message in batch if message.content)
        memory = await self.memory.retrieve(chat_id, query)
        instructions = build_instructions(memory, query=query)

        # Deterministic preflight: explicit GitHub inspection requests must fetch
        # the requested source before the LLM is allowed to answer from inference.
        github_evidence = await self._github_preflight(query)
        if github_evidence:
            instructions += "\n\n" + github_evidence

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

        openai_messages = self.context_manager.trim_messages(openai_messages)
        instructions = self.context_manager.trim_instructions(instructions)

        async with self.session_factory() as session:

            async def handle_tool(name: str, args: dict) -> str:
                capability = self.capabilities.get(name)
                if capability is not None:
                    result = await self.capability_executor.run(name, args)
                    return result.output
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

    async def _github_preflight(self, query: str) -> str:
        if not re.search(r"github|репозитор|readme|\.py\b|\.md\b", query, re.IGNORECASE):
            return ""
        repository_match = re.search(r"\b([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\b", query)
        path_match = re.search(r"(?:`|\b)([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.(?:py|md|txt|json|ya?ml|toml))(?:`|\b)", query)
        if not repository_match or not path_match:
            return ""
        repository = repository_match.group(1)
        path = path_match.group(1)
        result = await self.capability_executor.run(
            "github_read_file",
            {"repository": repository, "path": path, "ref": "main"},
        )
        return (
            "Verified GitHub evidence was fetched before answering. "
            "Use this evidence as the source of truth for the requested inspection:\n"
            + result.output
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
