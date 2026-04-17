#!/usr/bin/env bash
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

exec .venv/bin/python -m uvicorn app.main:app --reload --port 8000 --host 0.0.0.0
