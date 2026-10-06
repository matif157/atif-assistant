#!/usr/bin/env bash
# Start Raees. Loads .env if present, then runs the server.
set -euo pipefail
cd "$(dirname "$0")"

export PATH="$HOME/.local/bin:$PATH"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

PORT="${RAEES_PORT:-8770}"

echo "Raees  ->  http://127.0.0.1:${PORT}"
exec .venv/bin/python -m uvicorn raees.app:app \
  --host "${RAEES_HOST:-127.0.0.1}" \
  --port "${PORT}"