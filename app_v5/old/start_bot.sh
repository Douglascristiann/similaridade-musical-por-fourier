#!/usr/bin/env bash
set -euo pipefail

# Resolve project root (this script is expected in ./scripts/)
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")"/.. && pwd)"
cd "$ROOT"

mkdir -p logs

# If BOT_TOKEN is not set, the bot will try app_v5/integrations/.env
if [ -z "${BOT_TOKEN:-}" ]; then
  echo "[info] BOT_TOKEN não exportado; o bot tentará ler de app_v5/integrations/.env"
fi

export PYTHONPATH="$ROOT:${PYTHONPATH:-}"

echo "[info] Iniciando BOT em background..."
nohup python -m app_v5.integrations.menu_bot >> logs/bot.out 2>> logs/bot.err &
echo $! > logs/bot.pid
echo "[ok] Bot rodando. PID=$(cat logs/bot.pid)  | logs: logs/bot.out, logs/bot.err"
