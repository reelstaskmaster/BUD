#!/bin/sh
set -eu

mkdir -p "$HERMES_HOME"
cat > "$HERMES_HOME/config.yaml" <<'EOF'
providers:
  freellmapi:
    api: http://freellmapi:3001/v1
    key_env: FREELLMAPI_API_KEY
    transport: chat_completions

model:
  provider: custom:freellmapi
  default: auto
EOF

exec hermes gateway
