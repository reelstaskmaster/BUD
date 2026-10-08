# BUD / Hermes — ready-to-run status

## Architecture

BUD is the user-facing Telegram agent.

- **Hermes** — coordinator and autonomous loop
- **FreeLLMAPI** — model gateway
- **PostgreSQL + pgvector** — persistent memory
- **Claudex** — independent planning/result review
- **MCP boundary** — explicit server/tool allowlists
- **Skills** — reviewed procedures
- **Chrome DevTools MCP** — optional read-only browser observability
- **Sandbox integrations** — isolated execution candidates
- **Agent Zero** — optional isolated subordinate specialist

## What is already implemented

The core bot can:
- receive text, voice/audio and images through Telegram;
- transcribe audio;
- use persistent memory;
- route model requests through FreeLLMAPI;
- execute explicitly registered capabilities;
- inspect and modify GitHub through allowlisted capabilities;
- run bounded autonomous phases;
- run independent Claudex reviews;
- use explicitly configured MCP servers;
- generate images.

## What was missing compared with a full general-purpose agent

1. A dedicated isolated execution environment for arbitrary computer/code work.
2. A full browser execution layer rather than only a safe read-only browser MCP profile.
3. A clear subordinate-agent boundary so a powerful general-purpose agent does not become a second coordinator.
4. A production runbook that separates local smoke testing from real credentials.

Agent Zero is now catalogued for item 1/3. It is deliberately **not** auto-started.

## Launch order

### Phase 1 — safe smoke test

Run BUD with PostgreSQL and only the existing built-in capabilities.

Verify:
- Telegram responds;
- FreeLLMAPI responds;
- memory writes/reads;
- GitHub read works;
- GitHub writes stay on a feature branch;
- no MCP server is activated accidentally.

### Phase 2 — browser

Activate the pinned Chrome DevTools MCP profile only after the MCP stdio command is allow-listed.

### Phase 3 — isolated execution

Run Agent Zero or another sandboxed execution specialist in a disposable environment. Keep it behind the policy boundary.

### Phase 4 — production

Only after smoke tests pass:
- inject production Telegram credentials;
- inject model gateway credentials;
- enable webhook if desired;
- keep destructive capabilities approval-gated;
- monitor logs and resource usage.

## Current deployment blocker

The repository can be built and run with Docker, but an actual public deployment requires an available host/runtime and its credentials. The previously used Railway workspace was blocked by its billing/restriction state, so this repository must not pretend that production is live.

## Important

Do not copy Agent Zero into the Hermes coordinator. The goal is:

**BUD = Hermes + governed capabilities + isolated specialists.**

Not:

**BUD = Hermes + Agent Zero + another coordinator + another model gateway.**
