import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chat, Fact, Message, Summary


async def get_or_create_chat(session: AsyncSession, chat_id: int) -> Chat:
    chat = await session.get(Chat, chat_id)
    if chat is None:
        chat = Chat(id=chat_id)
        session.add(chat)
        await session.flush()
    return chat


async def add_message(
    session: AsyncSession,
    *,
    chat_id: int,
    role: str,
    content: str,
    media_type: str | None = None,
    telegram_file_id: str | None = None,
    answered: bool = False,
) -> Message:
    await get_or_create_chat(session, chat_id)
    message = Message(
        chat_id=chat_id,
        role=role,
        content=content,
        media_type=media_type,
        telegram_file_id=telegram_file_id,
        answered=answered,
    )
    session.add(message)
    await session.flush()
    return message


async def list_unanswered(session: AsyncSession, chat_id: int) -> list[Message]:
    result = await session.scalars(
        select(Message)
        .where(
            Message.chat_id == chat_id,
            Message.role == "user",
            Message.answered.is_(False),
        )
        .order_by(Message.created_at.asc())
    )
    return list(result.all())


async def mark_answered(session: AsyncSession, message_ids: list[uuid.UUID]) -> None:
    if not message_ids:
        return
    await session.execute(
        update(Message).where(Message.id.in_(message_ids)).values(answered=True)
    )


async def list_recent_messages(
    session: AsyncSession, chat_id: int, limit: int
) -> list[Message]:
    result = await session.scalars(
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    return list(reversed(result.all()))


async def list_messages_in_range(
    session: AsyncSession,
    chat_id: int,
    *,
    after: datetime | None,
    before: datetime,
) -> list[Message]:
    stmt = select(Message).where(
        Message.chat_id == chat_id,
        Message.created_at < before,
    )
    if after is not None:
        stmt = stmt.where(Message.created_at > after)
    stmt = stmt.order_by(Message.created_at.asc())
    result = await session.scalars(stmt)
    return list(result.all())


async def latest_summary(session: AsyncSession, chat_id: int) -> Summary | None:
    return await session.scalar(
        select(Summary)
        .where(Summary.chat_id == chat_id)
        .order_by(Summary.covered_until.desc())
        .limit(1)
    )


async def add_summary(
    session: AsyncSession,
    *,
    chat_id: int,
    content: str,
    embedding: list[float] | None,
    covered_until: datetime,
) -> Summary:
    summary = Summary(
        chat_id=chat_id,
        content=content,
        embedding=embedding,
        covered_until=covered_until,
    )
    session.add(summary)
    await session.flush()
    return summary


async def count_active_facts(session: AsyncSession, chat_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(Fact)
            .where(Fact.chat_id == chat_id, Fact.active.is_(True))
        )
        or 0
    )


async def list_active_facts(session: AsyncSession, chat_id: int) -> list[Fact]:
    result = await session.scalars(
        select(Fact)
        .where(Fact.chat_id == chat_id, Fact.active.is_(True))
        .order_by(Fact.updated_at.desc())
    )
    return list(result.all())


async def similar_facts(
    session: AsyncSession,
    chat_id: int,
    embedding: list[float],
    *,
    limit: int,
    active_only: bool = True,
) -> list[tuple[Fact, float]]:
    distance = Fact.embedding.cosine_distance(embedding)
    stmt = select(Fact, distance).where(
        Fact.chat_id == chat_id,
        Fact.embedding.is_not(None),
    )
    if active_only:
        stmt = stmt.where(Fact.active.is_(True))
    stmt = stmt.order_by(distance).limit(limit)
    rows = await session.execute(stmt)
    return [(fact, float(dist)) for fact, dist in rows.all()]


async def similar_summaries(
    session: AsyncSession,
    chat_id: int,
    embedding: list[float],
    *,
    limit: int,
) -> list[Summary]:
    distance = Summary.embedding.cosine_distance(embedding)
    stmt = (
        select(Summary)
        .where(Summary.chat_id == chat_id, Summary.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    )
    result = await session.scalars(stmt)
    return list(result.all())


async def add_fact(
    session: AsyncSession,
    *,
    chat_id: int,
    content: str,
    category: str,
    embedding: list[float] | None,
) -> Fact:
    fact = Fact(
        chat_id=chat_id,
        content=content,
        category=category,
        embedding=embedding,
        active=True,
    )
    session.add(fact)
    await session.flush()
    return fact


async def deactivate_facts(session: AsyncSession, fact_ids: list[uuid.UUID]) -> int:
    if not fact_ids:
        return 0
    result = await session.execute(
        update(Fact)
        .where(Fact.id.in_(fact_ids), Fact.active.is_(True))
        .values(active=False)
    )
    return int(result.rowcount or 0)
