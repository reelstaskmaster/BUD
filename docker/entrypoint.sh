#!/bin/sh
set -e

echo "Waiting for Postgres..."
python - <<'PY'
import asyncio
import os

import asyncpg

url = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://telegpt:telegpt@db:5432/telegpt",
)
dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)


async def wait() -> None:
    last_error: Exception | None = None
    for _ in range(60):
        try:
            conn = await asyncpg.connect(dsn)
            await conn.close()
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            await asyncio.sleep(1)
    raise RuntimeError(f"Postgres is not ready: {last_error}")


asyncio.run(wait())
PY

echo "Applying migrations..."
alembic upgrade head

echo "Starting bot..."
exec python -m app.main
