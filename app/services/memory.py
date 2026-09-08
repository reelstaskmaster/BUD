from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.db import repositories as repo
from app.db.models import Fact, Summary
from app.services.openai_client import OpenAIService
from app.services.prompt import MemoryContext

logger = logging.getLogger(__name__)

NEAR_DUPLICATE_DISTANCE = 0.18
FORGET_DISTANCE = 0.40
FACT_CATEGORIES = {"person", "interest", "preference", "name", "other"}


class MemoryService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        openai: OpenAIService,
        settings: Settings,
    ) -> None:
        self.session_factory = session_factory
        self.openai = openai
        self.settings = settings

    async def retrieve(self, chat_id: int, query: str) -> MemoryContext:
        async with self.session_factory() as session:
            profile = await repo.get_profile(session, chat_id)
            if not profile.memory_enabled:
                return MemoryContext(facts=[], summaries=[], profile=profile)
            fact_count = await repo.count_active_facts(session, chat_id)

            embedding: list[float] | None = None
            if query.strip():
                try:
                    embedding = await self.openai.embed(query)
                except Exception:
                    logger.exception("Failed to embed retrieval query")

            if fact_count == 0:
                facts: list[Fact] = []
            elif fact_count <= self.settings.fact_all_threshold or embedding is None:
                facts = await repo.list_active_facts(session, chat_id)
            else:
                ranked = await repo.similar_facts(
                    session,
                    chat_id,
                    embedding,
                    limit=self.settings.fact_top_k,
                )
                facts = [fact for fact, _dist in ranked]

            latest = await repo.latest_summary(session, chat_id)
            summaries: list[Summary] = []
            if latest:
                summaries.append(latest)
            if embedding is not None:
                nearest = await repo.similar_summaries(
                    session, chat_id, embedding, limit=1
                )
                for summary in nearest:
                    if latest is None or summary.id != latest.id:
                        summaries.append(summary)
            return MemoryContext(facts=facts, summaries=summaries, profile=profile)

    async def remember_fact(
        self, session: AsyncSession, chat_id: int, content: str, category: str
    ) -> str:
        if not content.strip():
            return "Nothing to remember."
        profile = await repo.get_profile(session, chat_id)
        if not profile.memory_enabled:
            return "Long-term memory is disabled."
        if not await repo.memory_is_writable(session, chat_id):
            await repo.freeze_expired_memory(session, chat_id)
            return "Long-term memory is currently frozen."
        category = category if category in FACT_CATEGORIES else "other"
        embedding = await self.openai.embed(content)
        duplicates = await repo.similar_facts(
            session, chat_id, embedding, limit=1, active_only=True
        )
        if duplicates and duplicates[0][1] <= NEAR_DUPLICATE_DISTANCE:
            return "That fact is already in memory."
        await repo.add_fact(
            session,
            chat_id=chat_id,
            content=content.strip(),
            category=category,
            embedding=embedding,
        )
        await session.commit()
        return "Fact stored."

    async def forget_fact(self, session: AsyncSession, chat_id: int, query: str) -> str:
        if not query.strip():
            return "Tell me what to forget."
        embedding = await self.openai.embed(query)
        matches = await repo.similar_facts(
            session, chat_id, embedding, limit=8, active_only=True
        )
        to_drop = [fact.id for fact, dist in matches if dist <= FORGET_DISTANCE]
        forgotten = await repo.deactivate_facts(session, to_drop)
        await session.commit()
        if forgotten:
            return f"Forgot {forgotten} matching fact(s)."
        return "No matching fact found to forget."

    async def tool_handler(
        self, session: AsyncSession, chat_id: int, name: str, args: dict[str, Any]
    ) -> str:
        if name == "remember_fact":
            return await self.remember_fact(
                session,
                chat_id,
                str(args.get("content") or ""),
                str(args.get("category") or "other"),
            )
        if name == "forget_fact":
            return await self.forget_fact(
                session, chat_id, str(args.get("query") or "")
            )
        return f"Unknown tool: {name}"

    async def maintain(self, chat_id: int) -> None:
        try:
            async with self.session_factory() as session:
                profile = await repo.get_profile(session, chat_id)
                if not profile.memory_enabled or not await repo.memory_is_writable(session, chat_id):
                    await repo.freeze_expired_memory(session, chat_id)
                    await session.commit()
                    return
            await self._extract_from_recent_turn(chat_id)
            await self._summarize_if_needed(chat_id)
        except Exception:
            logger.exception("Memory maintenance failed for chat %s", chat_id)

    async def _extract_from_recent_turn(self, chat_id: int) -> None:
        async with self.session_factory() as session:
            profile = await repo.get_profile(session, chat_id)
            if not profile.memory_enabled or not await repo.memory_is_writable(session, chat_id):
                return
            recent = await repo.list_recent_messages(
                session, chat_id, limit=min(8, self.settings.recent_messages)
            )
        if not recent:
            return
        transcript = "\n".join(
            f"{message.role}: {message.content}" for message in recent[-6:]
        )
        items = await self.openai.extract_facts(transcript)
        if not items:
            return
        async with self.session_factory() as session:
            for item in items:
                content = str(item.get("content") or "").strip()
                if not content:
                    continue
                category = str(item.get("category") or "other")
                action = str(item.get("action") or "add").lower()
                if action == "forget":
                    await self.forget_fact(session, chat_id, content)
                else:
                    await self.remember_fact(session, chat_id, content, category)

    async def _summarize_if_needed(self, chat_id: int) -> None:
        async with self.session_factory() as session:
            profile = await repo.get_profile(session, chat_id)
            if not profile.memory_enabled or not await repo.memory_is_writable(session, chat_id):
                return
            recent = await repo.list_recent_messages(
                session, chat_id, self.settings.recent_messages
            )
            if len(recent) < self.settings.recent_messages:
                return
            cutoff = recent[0].created_at
            last = await repo.latest_summary(session, chat_id)
            after = last.covered_until if last else None
            uncovered = await repo.list_messages_in_range(
                session, chat_id, after=after, before=cutoff
            )
            if len(uncovered) < self.settings.summarize_every:
                return
            transcript = "\n".join(
                f"{message.role}: {message.content}"
                for message in uncovered
                if message.content
            )
            if not transcript.strip():
                return

        summary_text = await self.openai.summarize(transcript)
        if not summary_text:
            return
        try:
            embedding = await self.openai.embed(summary_text)
        except Exception:
            logger.exception("Failed to embed summary")
            embedding = None

        async with self.session_factory() as session:
            profile = await repo.get_profile(session, chat_id)
            if not profile.memory_enabled or not await repo.memory_is_writable(session, chat_id):
                return
            await repo.add_summary(
                session,
                chat_id=chat_id,
                content=summary_text,
                embedding=embedding,
                covered_until=uncovered[-1].created_at,
            )
            await session.commit()
