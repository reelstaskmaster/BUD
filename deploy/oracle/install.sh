#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/bud}"

echo "[1/5] Checking prerequisites"
command -v docker >/dev/null || { echo "Docker is required."; exit 1; }
docker compose version >/dev/null || { echo "Docker Compose plugin is required."; exit 1; }

echo "[2/5] Preparing application directory"
mkdir -p "$APP_DIR"
cd "$APP_DIR"

echo "[3/5] Getting BUD source"
if [ -d .git ]; then
  git fetch --prune origin
  git checkout main
  git pull --ff-only origin main
else
  git clone https://github.com/reelstaskmaster/BUD.git .
fi

echo "[4/5] Configuring secrets"
if [ ! -f deploy/oracle/.env ]; then
  cp deploy/oracle/.env.example deploy/oracle/.env
  chmod 600 deploy/oracle/.env
  echo "Edit $APP_DIR/deploy/oracle/.env before starting BUD."
  exit 0
fi

echo "[5/5] Starting BUD"
docker compose --env-file deploy/oracle/.env -f deploy/oracle/docker-compose.yml up -d --build
docker compose --env-file deploy/oracle/.env -f deploy/oracle/docker-compose.yml ps

echo "BUD deployment started. Logs: docker compose --env-file deploy/oracle/.env -f deploy/oracle/docker-compose.yml logs -f bot"
