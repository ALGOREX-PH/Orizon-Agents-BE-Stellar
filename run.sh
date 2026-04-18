#!/usr/bin/env bash
# Local dev runner. Production hosts (Render/Fly/Cloud Run) inject $PORT
# and call uvicorn directly — this script is for `./run.sh` on your laptop.
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "→ creating virtualenv"
  uv venv .venv
  uv pip install -r requirements.txt
fi

if [ ! -f ".env" ]; then
  echo "→ no .env; copy .env.example and set OPENAI_API_KEY"
  cp .env.example .env
  exit 1
fi

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
RELOAD="${RELOAD:---reload}"

exec .venv/bin/python -m uvicorn app.main:app $RELOAD --port "$PORT" --host "$HOST"
