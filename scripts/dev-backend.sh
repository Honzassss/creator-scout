#!/usr/bin/env bash
# Start the FastAPI backend on :8000 (mock mode by default, no keys needed).
# Env vars are read from the environment and /.env (see .env.example); SOURCE_MODE defaults to mock.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"
if [ ! -x .venv/bin/uvicorn ]; then
  echo "backend/.venv missing: python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt" >&2
  exit 1
fi
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}" "$@"
