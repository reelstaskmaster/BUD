import calendar
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chat, Fact, GenerationBalance, MemoryAccess, Message, Summary, UserProfile

TRIAL_DURATION = timedelta(days=3)
FREE_GENERATIONS = 3


def add_calendar_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


async def get_or_create_chat(session: AsyncSession, chat_id: int) -> Chat:
    chat = await session.get(Chat, chat_id)
    if chat is None:
        chat = Chat(id=chat_id)
        session.add(chat)
        await session.flush()
        now = datetime.now(timezone.utc)
        session.add(UserProfile(chat_id=chat_id))
        session.add(MemoryAccess(chat_id=chat_id, trial_started_at=now, trial_ends_at=now + TRIAL_DURATION))
        session.add(GenerationBalance(chat_id=chat_id, free_remaining=FREE_GENERATIONS))
        await session.flush()
    else:
        if await session.get(UserProfile, chat_id) is None:
            session.add(UserProfile(chat_id=chat_id))
        if await session.get(MemoryAccess, chat_id) is None:
            now = datetime.now(timezone.utc)
            session.add(MemoryAccess(chat_id=chat_id, trial_started_at=now, trial_ends_at=now + TRIAL_DURATION))
        if await session.get(GenerationBalance, chat_id) is None:
            session.add(GenerationBalance(chat_id=chat_id, free_remaining=FREE_GENERATIONS))
        await session.flush()
    return chat


async def get_profile(session: AsyncSession, chat_id: int) -> UserProfile:
    await get_or_create_chat(session, chat_id)
    profile = await session.get(UserProfile, chat_id)
    assert profile is not None
    return profile


async def save_profile(session: AsyncSession, chat_id: int, *, preferences: dict | None = None, about: str | None = None, onboarding_complete: bool | None = None, onboarding_step: int | None = None) -> UserProfile:
    profile = await get_profile(session, chat_id)
    if preferences is not None:
        profile.preferences = preferences
    if about is not None:
        profile.about = about
    if onboarding_complete is not None:
        profile.onboarding_complete = onboarding_complete
    if onboarding_step is not None:
        profile.onboarding_step = onboarding_step
    await session.flush()
    return profile


async def get_memory_access(session: AsyncSession, chat_id: int) -> MemoryAccess:
    await get_or_create_chat(session, chat_id)
    access = await session.get(MemoryAccess, chat_id)
    assert access is not None
    return access


async def memory_is_writable(session: AsyncSession, chat_id: int) -> bool:
    access = await get_memory_access(session, chat_id)
    now = datetime.now(timezone.utc)
    return bool((access.paid_ends_at and now < access.paid_ends_at) or now < access.trial_ends_at)


async def grant_paid_memory(session: AsyncSession, chat_id: int) -> MemoryAccess:
    access = await get_memory_access(session, chat_id)
    now = datetime.now(timezone.utc)
    start = access.paid_ends_at if access.paid_ends_at and access.paid_ends_at > now else now
    if access.paid_started_at is None:
        access.paid_started_at = now
    # One paid month + one gift month = two calendar months of memory access.
    access.paid_ends_at = add_calendar_months(start, 2)
    access.frozen_at = None
    await session.flush()
    return access


async def freeze_expired_memory(session: AsyncSession, chat_id: int) -> bool:
    access = await get_memory_access(session, chat_id)
    now = datetime.now(timezone.utc)
    if access.paid_ends_at and now >= access.paid_ends_at and access.frozen_at is None:
        access.frozen_at = now
        await session.flush()
        return True
    if access.paid_ends_at is None and now >= access.trial_ends_at and access.frozen_at is None:
        access.frozen_at = now
        await session.flush()
        return True
    return False


async def get_generation_balance(session: AsyncSession, chat_id: int) -> GenerationBalance:
    await get_or_create_chat(session, chat_id)
    balance = await session.get(GenerationBalance, chat_id)
    assert balance is not None
    return balance


async def consume_generation(session: AsyncSession, chat_id: int) -> bool:
    balance = await get_generation_balance(session, chat_id)
    if balance.free_remaining > 0:
        balance.free_remaining -= 1
    elif balance.purchased_remaining > 0:
        balance.purchased_remaining -= 1
    else:
        return False
    balance.total_generated += 1
    await session.flush()
    return True


async def add_purchased_generations(session: AsyncSession, chat_id: int, amount: int) -> GenerationBalance:
    if amount <= 0:
        raise ValueError("Generation amount must be positive")
    balance = await get_generation_balance(session, chat_id)
    balance.purchased_remaining += amount
    await session.flush()
    return balance


async def add_message(session: AsyncSession, *, chat_id: int, role: str, content: str, media_type: str | None = None, telegram_file_id: str | None = None, answered: bool = False) -> Message:
    await get_or_create_chat(session, chat_id)
    message = Message(chat_id=chat_id, role=role, content=content, media_type=media_type, telegram_file_id=telegram_file_id, answered=answered)
    session.add(message)
    await session.flush()
    return message


async def list_unanswered(session: AsyncSession, chat_id: int) -> list[Message]:
    result = await session.scalars(select(Message).where(Message.chat_id == chat_id, Message.role == "user", Message.answered.is_(False)).order_by(Message.created_at.asc()))
    return list(result.all())


async def mark_answered(session: AsyncSession, message_ids: list[uuid.UUID]) -> None:
    if not message_ids:
        return
    await session.execute(update(Message).where(Message.id.in_(message_ids)).values(answered=True))


async def list_recent_messages(session: AsyncSession, chat_id: int, limit: int) -> list[Message]:
    result = await session.scalars(select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at.desc()).limit(limit))
    return list(reversed(result.all()))


async def list_messages_in_range(session: AsyncSession, chat_id: int, *, after: datetime | None, before: datetime) -> list[Message]:
    stmt = select(Message).where(Message.chat_id == chat_id, Message.created_at < before)
    if after is not None:
        stmt = stmt.where(Message.created_at > after)
    result = await session.scalars(stmt.order_by(Message.created_at.asc()))
    return list(result.all())


async def latest_summary(session: AsyncSession, chat_id: int) -> Summary | None:
    return await session.scalar(select(Summary).where(Summary.chat_id == chat_id).order_by(Summary.covered_until.desc()).limit(1))


async def add_summary(session: AsyncSession, *, chat_id: int, content: str, embedding: list[float] | None, covered_until: datetime) -> Summary:
    summary = Summary(chat_id=chat_id, content=content, embedding=embedding, covered_until=covered_until)
    session.add(summary)
    await session.flush()
    return summary


async def count_active_facts(session: AsyncSession, chat_id: int) -> int:
    return int(await session.scalar(select(func.count()).select_from(Fact).where(Fact.chat_id == chat_id, Fact.active.is_(True))) or 0)


async def list_active_facts(session: AsyncSession, chat_id: int) -> list[Fact]:
    result = await session.scalars(select(Fact).where(Fact.chat_id == chat_id, Fact.active.is_(True)).order_by(Fact.updated_at.desc()))
    return list(result.all())


async def similar_facts(session: AsyncSession, chat_id: int, embedding: list[float], *, limit: int, active_only: bool = True) -> list[tuple[Fact, float]]:
    distance = Fact.embedding.cosine_distance(embedding)
    stmt = select(Fact, distance).where(Fact.chat_id == chat_id, Fact.embedding.is_not(None))
    if active_only:
        stmt = stmt.where(Fact.active.is_(True))
    rows = await session.execute(stmt.order_by(distance).limit(limit))
    return [(fact, float(dist)) for fact, dist in rows.all()]


async def similar_summaries(session: AsyncSession, chat_id: int, embedding: list[float], *, limit: int) -> list[Summary]:
    distance = Summary.embedding.cosine_distance(embedding)
    result = await session.scalars(select(Summary).where(Summary.chat_id == chat_id, Summary.embedding.is_not(None)).order_by(distance).limit(limit))
    return list(result.all())


async def add_fact(session: AsyncSession, *, chat_id: int, content: str, category: str, embedding: list[float] | None) -> Fact:
    fact = Fact(chat_id=chat_id, content=content, category=category, embedding=embedding, active=True)
    session.add(fact)
    await session.flush()
    return fact


async def deactivate_facts(session: AsyncSession, fact_ids: list[uuid.UUID]) -> int:
    if not fact_ids:
        return 0
    result = await session.execute(update(Fact).where(Fact.id.in_(fact_ids), Fact.active.is_(True)).values(active=False))
    return int(result.rowcount or 0)
