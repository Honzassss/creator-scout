#!/usr/bin/env bash
# Start the Vite dev server on :5173; /api is proxied to the backend on 127.0.0.1:8000 (API_TARGET overrides).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/frontend"
[ -d node_modules ] || npm install
exec npm run dev -- --host 127.0.0.1 --port "${PORT:-5173}" --strictPort "$@"
