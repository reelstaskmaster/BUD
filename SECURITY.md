# BUD Security Baseline

## Current architecture

BUD uses the official Hermes Agent runtime. The repository does not contain a custom agent loop.

## Current hardening

- Official versioned Hermes Docker image.
- Official image entrypoint/s6 supervision is preserved.
- No host networking.
- No published API/dashboard ports.
- API server explicitly disabled.
- Gateway global allow-all explicitly disabled.
- Telegram allow-all explicitly disabled.
- Telegram/global allowlists are expected to be configured before exposing the bot.
- Hermes terminal backend is Docker.
- Host environment forwarding to terminal is empty.
- Current working directory is not mounted into the terminal sandbox.
- Resource limits are set for CPU, memory, and disk.
- MCP discovery concurrency is limited to one server at a time.
- Repository config and SOUL are mounted read-only into the Hermes data directory.
- Secrets remain in `hermes-data/.env`, which is gitignored.

## MCP integration gate

The following candidates are NOT integrated yet:

- GitHub MCP
- Filesystem MCP
- Playwright MCP

Each must pass source review, dependency/advisory review, permission review, isolated runtime testing, and a final re-check before integration.

## Important security decisions

### GitHub MCP

Use only the official GitHub MCP Server. Start with read-only mode, lockdown mode, and the smallest toolset. GitHub's lockdown mode is a prompt-injection mitigation, not an authorization boundary.

Do not give the server a token with unnecessary repository or organization permissions.

### Filesystem MCP

If approved, pin a reviewed version and expose only a dedicated BUD workspace directory. Never expose the Windows user profile, SSH directory, browser profile, credential stores, or the whole drive.

### Playwright MCP

Do not connect it to a personal browser profile. Use an isolated Chromium instance. Keep the MCP endpoint local to the trusted client/container. Treat webpage content and accessibility snapshots as untrusted input.

Playwright MCP itself is not a security boundary; isolation must come from the surrounding execution environment and policy.

## Verification standard

These states are distinct:

- REVIEWED: static inspection completed.
- SANDBOXED: candidate actually executed in an isolated environment.
- VERIFIED: required security and functional tests passed.
- INTEGRATED: only after VERIFIED.

Never report one state as another.
