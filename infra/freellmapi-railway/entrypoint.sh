#!/bin/sh
set -eu

mkdir -p /opt/data
cat > /opt/data/config.yaml <<'EOF'
custom_providers:
  - name: freellmapi
    base_url: http://freellmapi:3001/v1
    key_env: FREELLMAPI_API_KEY
model:
  provider: custom:freellmapi
  default: auto
EOF

exec hermes gateway
