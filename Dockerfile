FROM python:3.12-slim-bookworm

WORKDIR /app

COPY pyproject.toml requirements.txt alembic.ini ./
COPY app ./app
COPY alembic ./alembic
COPY docker/entrypoint.sh /entrypoint.sh

RUN pip install --no-cache-dir -e . \
    && chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
