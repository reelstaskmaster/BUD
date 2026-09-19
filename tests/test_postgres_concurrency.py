import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import repositories as repo
from app.db.models import Chat, ReplyDelivery

pytestmark = pytest.mark.asyncio


def _database_url() -> str:
    return os.environ["DATABASE_URL"]


@pytest_asyncio.fixture
async def db_session_factory():
    engine = create_async_engine(_database_url(), pool_size=5, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


async def test_chat_processing_lease_allows_only_one_owner(db_session_factory) -> None:
    chat_id = -910000001
    async with db_session_factory() as session:
        await session.execute(ReplyDelivery.__table__.delete().where(ReplyDelivery.chat_id == chat_id))
        await session.execute(Chat.__table__.delete().where(Chat.id == chat_id))
        await repo.get_or_create_chat(session, chat_id)
        await session.commit()

    async def claim(owner: str) -> bool:
        async with db_session_factory() as session:
            claimed = await repo.claim_chat_processing(session, chat_id, owner)
            await session.commit()
            return claimed

    first, second = await asyncio.gather(claim("owner-a"), claim("owner-b"))
    assert sorted((first, second)) == [False, True]

    async with db_session_factory() as session:
        await repo.release_chat_processing(session, chat_id, "owner-a")
        await repo.release_chat_processing(session, chat_id, "owner-b")
        await session.commit()


async def test_reply_delivery_creation_is_idempotent_under_race(
    db_session_factory,
) -> None:
    chat_id = -910000002
    source_ids = [uuid.uuid4(), uuid.uuid4()]

    async with db_session_factory() as session:
        await repo.get_or_create_chat(session, chat_id)
        await session.commit()

    async def create() -> uuid.UUID:
        async with db_session_factory() as session:
            delivery = await repo.create_reply_delivery(
                session,
                chat_id=chat_id,
                source_message_ids=source_ids,
                content="race-test",
                media_type="text",
                image_bytes=None,
            )
            await session.commit()
            return delivery.id

    first, second = await asyncio.gather(create(), create())
    assert first == second

    async with db_session_factory() as session:
        pending = await repo.list_pending_reply_deliveries(session, chat_id)
        assert len(pending) == 1
        await session.execute(
            ReplyDelivery.__table__.delete().where(
                repo.ReplyDelivery.chat_id == chat_id
            )
        )
        await session.commit()

    async with db_session_factory() as session:
        await repo.release_chat_processing(session, chat_id, "owner-a")
        await repo.release_chat_processing(session, chat_id, "owner-b")
        await session.execute(
            Chat.__table__.delete().where(repo.Chat.id == chat_id)
        )
        await session.commit()
