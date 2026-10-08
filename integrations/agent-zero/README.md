# Agent Zero subordinate integration

Agent Zero is treated as an **isolated subordinate execution specialist**, not as the BUD/Hermes coordinator.

## Boundary

```
Telegram -> Hermes -> policy boundary -> Agent Zero sandbox
                              |
                              +-> browser / terminal / skills / projects
                              |
                              +-> result -> Hermes -> user
```

Hermes remains the coordinator and FreeLLMAPI remains the model gateway.

Agent Zero must not receive:
- production Telegram bot tokens;
- FreeLLMAPI credentials;
- unrestricted host filesystem mounts;
- unrestricted network access;
- direct write access to the BUD `main` branch.

Use a disposable workspace and short-lived credentials for untrusted work.

## Why it is useful

The upstream project provides a Dockerized general-purpose agent with persistent memory, browser automation, skills, project isolation, multi-agent cooperation and MCP/A2A connectivity.

Those features fill a real gap in BUD: a general execution environment. They do **not** justify replacing Hermes.

## Activation policy

This directory is documentation/configuration only. It does not install or start Agent Zero.

Before activation:
1. Pin an exact Agent Zero image/version.
2. Review the image provenance and release.
3. Run it with a dedicated non-production workspace.
4. Deny host mounts by default.
5. Deny unrestricted egress by default.
6. Expose the UI only on loopback/private networking.
7. Add an explicit MCP/A2A allowlist.
8. Test with harmless tasks first.
9. Keep human approval for destructive/write operations.

## Recommended first smoke test

Ask the subordinate agent to:
1. create a file inside its disposable workspace;
2. read it back;
3. perform a harmless browser read;
4. report exactly what it changed.

Do not test against the production BUD repository or real secrets.

## Status

`review_required` — intentionally not auto-started.
