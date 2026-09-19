import uuid
from datetime import datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chat, Fact, Message, ReplyDelivery, Summary


async def get_or_create_chat(session: AsyncSession, chat_id: int) -> Chat:
    chat = await session.get(Chat, chat_id)
    if chat is None:
        await session.execute(
            pg_insert(Chat)
            .values(id=chat_id)
            .on_conflict_do_nothing(index_elements=[Chat.id])
        )
        chat = await session.get(Chat, chat_id)
        if chat is None:
            raise RuntimeError(f"Failed to create chat {chat_id}")
    return chat


async def add_message(
    session: AsyncSession,
    *,
    chat_id: int,
    role: str,
    content: str,
    media_type: str | None = None,
    telegram_message_id: int | None = None,
    telegram_file_id: str | None = None,
    media_mime_type: str | None = None,
    answered: bool = False,
) -> Message:
    await get_or_create_chat(session, chat_id)
    values = {
        "chat_id": chat_id,
        "role": role,
        "content": content,
        "media_type": media_type,
        "telegram_message_id": telegram_message_id,
        "telegram_file_id": telegram_file_id,
        "media_mime_type": media_mime_type,
        "answered": answered,
    }
    if telegram_message_id is not None:
        result = await session.execute(
            pg_insert(Message)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[Message.chat_id, Message.telegram_message_id]
            )
            .returning(Message.id)
        )
        message_id = result.scalar_one_or_none()
        if message_id is None:
            message = await session.scalar(
                select(Message).where(
                    Message.chat_id == chat_id,
                    Message.telegram_message_id == telegram_message_id,
                )
            )
            if message is None:
                raise RuntimeError(
                    f"Telegram message {telegram_message_id} disappeared during deduplication"
                )
            return message
        message = await session.get(Message, message_id)
        if message is None:
            raise RuntimeError(f"Inserted message {message_id} disappeared")
        return message

    message = Message(**values)
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
        .order_by(Message.created_at.asc(), Message.id.asc())
    )
    return list(result.all())


async def mark_answered(session: AsyncSession, message_ids: list[uuid.UUID]) -> None:
    if not message_ids:
        return
    await session.execute(
        update(Message)
        .where(
            Message.id.in_(message_ids),
            Message.role == "user",
            Message.answered.is_(False),
        )
        .values(answered=True)
    )


async def list_recent_messages(
    session: AsyncSession, chat_id: int, limit: int
) -> list[Message]:
    result = await session.scalars(
        select(Message)
        .where(Message.chat_id == chat_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
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
    stmt = stmt.order_by(Message.created_at.asc(), Message.id.asc())
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


async def claim_chat_processing(
    session: AsyncSession, chat_id: int, owner: str
) -> bool:
    result = await session.execute(
        update(Chat)
        .where(
            Chat.id == chat_id,
            (
                Chat.processing_until.is_(None)
                | (Chat.processing_until < func.now())
                | (Chat.processing_owner == owner)
            ),
        )
        .values(
            processing_owner=owner,
            processing_until=func.now() + text("interval '15 minutes'"),
        )
        .returning(Chat.id)
    )
    return result.scalar_one_or_none() is not None


async def release_chat_processing(
    session: AsyncSession, chat_id: int, owner: str
) -> None:
    await session.execute(
        update(Chat)
        .where(Chat.id == chat_id, Chat.processing_owner == owner)
        .values(processing_owner=None, processing_until=None)
    )


async def renew_chat_processing(
    session: AsyncSession, chat_id: int, owner: str
) -> bool:
    result = await session.execute(
        update(Chat)
        .where(Chat.id == chat_id, Chat.processing_owner == owner)
        .values(processing_until=func.now() + text("interval '15 minutes'"))
        .returning(Chat.id)
    )
    return result.scalar_one_or_none() is not None

    
async def create_reply_delivery(
    session: AsyncSession,
    *,
    chat_id: int,
    source_message_ids: list[uuid.UUID],
    content: str,
    media_type: str,
    image_bytes: bytes | None,
) -> ReplyDelivery:
    delivery = ReplyDelivery(
        chat_id=chat_id,
        source_message_ids=[str(item) for item in source_message_ids],
        content=content,
        media_type=media_type,
        image_bytes=image_bytes,
        status="pending",
        attempts=0,
    )
    session.add(delivery)
    await session.flush()
    return delivery


async def mark_reply_delivery_sent(
    session: AsyncSession, delivery_id: uuid.UUID
) -> None:
    await session.execute(
        update(ReplyDelivery)
        .where(ReplyDelivery.id == delivery_id, ReplyDelivery.status == "pending")
        .values(status="sent", sent_at=func.now())
    )


async def mark_reply_delivery_attempt(
    session: AsyncSession, delivery_id: uuid.UUID, error: str
) -> None:
    await session.execute(
        update(ReplyDelivery)
        .where(ReplyDelivery.id == delivery_id, ReplyDelivery.status == "pending")
        .values(
            attempts=ReplyDelivery.attempts + 1,
            last_error=error[:2000],
        )
    )


async def list_pending_reply_deliveries(
    session: AsyncSession, chat_id: int, limit: int = 5
) -> list[ReplyDelivery]:
    result = await session.scalars(
        select(ReplyDelivery)
        .where(
            ReplyDelivery.chat_id == chat_id,
            ReplyDelivery.status == "pending",
        )
        .order_by(ReplyDelivery.created_at.asc())
        .limit(limit)
    )
    return list(result.all())
