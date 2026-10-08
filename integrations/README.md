# Agent integrations

Hermes/BUD keeps third-party agent components behind an explicit integration boundary.

## Rule

A component in this directory is **not installed or activated merely because it is catalogued**.

Every component must pass:
1. provenance/license review;
2. dependency and install-script review;
3. permission/capability review;
4. sandbox test;
5. integration test;
6. explicit activation.

## Current stack

- Chrome DevTools MCP: configured, pinned, read-only policy.
- AIO Sandbox: review required; upstream examples use `seccomp=unconfined`.
- MCP Agent Security Gateway: review required; research prototype.
- agentgateway: review required; do not duplicate FreeLLMAPI until architecture is compared.
- agent-memory: review required; promising human-governed memory.
- agent-memory-mcp: review required; allowlist repository paths before activation.
- Flue: review required; reference architecture only, not a second coordinator.

## Security boundary

Hermes remains the coordinator. Third-party components are tools/infrastructure behind policy enforcement. They must not gain unrestricted access to secrets, the host filesystem, arbitrary network egress, or production credentials.

Never use floating `@latest` dependencies for production activation.
