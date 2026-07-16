#!/usr/bin/env bash
# Boots the hotel-search-agent leaf locally on port 8101 (AgentB2C range:
# 8100 concierge / 8101 search / 8102 faq — the fleet occupies 8092/8093).
# Sources repo-root .env if present; safe local defaults otherwise. No LLM/MCP
# call happens at boot (lazy connections) — booting needs no real credentials.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

export PORT="${PORT:-8101}"
# Local default only — serve.py fails closed without a token (D7); deploys use a real secret.
export A2A_BEARER_TOKEN="${A2A_BEARER_TOKEN:-local-dev-token}"

UVICORN="$ROOT/.venv/bin/uvicorn"
[ -x "$UVICORN" ] || UVICORN="uvicorn"

cd agents/hotel_search_agent
exec "$UVICORN" serve:app --port "$PORT"
