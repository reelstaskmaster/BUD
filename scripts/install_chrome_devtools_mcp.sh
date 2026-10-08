#!/usr/bin/env bash
set -euo pipefail

VERSION="1.10.1"

command -v node >/dev/null || { echo "Node.js is required"; exit 1; }
command -v npm >/dev/null || { echo "npm is required"; exit 1; }

node_major="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$node_major" -lt 20 ]; then
  echo "Chrome DevTools MCP requires Node.js 20+"
  exit 1
fi

# Install the exact reviewed release into the local npm cache.
# BUD still controls activation through MCP_SERVERS_JSON.
npm cache add "chrome-devtools-mcp@${VERSION}"

echo "Reviewed Chrome DevTools MCP ${VERSION} is available."
echo "Do not activate it until Chrome and the MCP policy have been reviewed."
