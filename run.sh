#!/usr/bin/env bash
# Start FinGraph AI on http://127.0.0.1:8720 (builds the web app first if needed).
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d web/dist ]; then
  (cd web && npm install --no-audit --no-fund && npm run build)
fi
uv sync --quiet
exec uv run uvicorn fingraph.api:app --host 127.0.0.1 --port "${PORT:-8720}"
