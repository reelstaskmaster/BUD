# BUD

BUD is the name and identity of an installation of Hermes Agent.

## Runtime

The project intentionally contains no custom agent framework. Hermes provides the agent loop, memory, terminal, browser, skills, subagents, and MCP runtime.

## Local startup

First run the Hermes setup wizard:

```powershell
docker compose run --rm bud setup
```

Then start the gateway:

```powershell
docker compose up -d
docker compose logs -f bud
```

Before exposing Telegram, configure `TELEGRAM_BOT_TOKEN` and a strict `TELEGRAM_ALLOWED_USERS` list in `hermes-data/.env`.

## Security

Read `SECURITY.md` before adding any third-party MCP or skill.

No third-party MCP is installed by default. Candidates must pass the security gate and an actual sandbox test before integration.
