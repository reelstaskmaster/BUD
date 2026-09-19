# Local BUD setup

## Windows

From the repository root:

```powershell
py -m pip install -r requirements.txt
py -m app.main
```

The project requires Python 3.12+.

Create a local `.env` from `.env.example` and provide the required Telegram and OpenAI credentials. Never commit `.env`.

BUD also requires PostgreSQL with the pgvector extension. The repository's Docker setup can provide the database when Docker is available.

## Why requirements.txt is important

`requirements.txt` is kept in sync with `pyproject.toml` so a fresh Windows environment does not miss runtime packages such as aiogram and SQLAlchemy.
