#!/bin/sh
set -eu

node server/dist/index.js &
pid=$!

for i in $(seq 1 90); do
  if [ -f /app/server/data/freeapi.db ]; then
    break
  fi
  sleep 1
done

if [ ! -f /app/server/data/freeapi.db ]; then
  echo "FreeLLMAPI database did not appear before synchronization timeout" >&2
  wait "$pid"
  exit $?
fi

cd /app/server
node -e '
const Database = require("better-sqlite3");
const db = new Database("/app/server/data/freeapi.db");
const key = process.env.FREEAPI_BOOTSTRAP_KEY;
if (!key) throw new Error("FREEAPI_BOOTSTRAP_KEY is not set");
const result = db.prepare("UPDATE settings SET value=? WHERE key=?").run(key, "unified_api_key");
if (result.changes !== 1) throw new Error("unified_api_key setting was not updated");
const check = db.prepare("SELECT value FROM settings WHERE key=?").get("unified_api_key");
db.close();
if (!check || check.value !== key) throw new Error("unified_api_key verification failed");
console.log("FreeLLMAPI unified API key synchronized");
'

wait "$pid"
