# Safe agent integrations

This directory contains reviewed, opt-in MCP configurations for BUD/Hermes.

## Chrome DevTools MCP

Source: ChromeDevTools/chrome-devtools-mcp
Pinned release: 1.10.1
License: Apache-2.0

The checked-in configuration deliberately uses:
- pinned npm version (not @latest);
- slim/headless mode;
- usage-statistics opt-out;
- an explicit allowlist of four read-only tools;
- no write/destructive tools.

Do not widen the tool allowlist without a security review.

The configuration is data until BUD explicitly loads it through MCP_SERVERS_JSON.
