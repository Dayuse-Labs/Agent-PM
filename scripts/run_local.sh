#!/usr/bin/env bash
# Boots the 3 AgentB2C services locally (AgentB2C port range; the fleet occupies 8092/8093):
#   b2c-concierge :8100 · hotel-search-agent :8101 · faq-agent :8102
# Background processes with pidfiles + logs under .run-logs/ (gitignored).
# Sources repo-root .env if present; safe local defaults otherwise. No LLM/MCP
# call happens at boot (lazy connections) — booting needs no real credentials.
#
#   bash scripts/run_local.sh          # start the 3 services (idempotent: stops leftovers first)
#   bash scripts/run_local.sh stop     # stop them
#
# PORT_OFFSET (default 0, so default behavior is unchanged): shifts all 3
# ports by this amount, e.g. PORT_OFFSET=10 -> 8110/8111/8112. For running a
# second stack side-by-side (a parallel worktree already holding 8100-8102) —
# pidfiles/logs also move under .run-logs/, one per offset, so two stacks
# started from different worktrees never collide on files either.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT_OFFSET="${PORT_OFFSET:-0}"

RUN_DIR="$ROOT/.run-logs"
[ "$PORT_OFFSET" != "0" ] && RUN_DIR="$RUN_DIR/offset-$PORT_OFFSET"
mkdir -p "$RUN_DIR"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# MCP_B2C_URL_OVERRIDE: points this stack at another MCP (e.g. a branch build on
# :8180) — .env would otherwise win over an exported MCP_B2C_URL.
if [ -n "${MCP_B2C_URL_OVERRIDE:-}" ]; then
  export MCP_B2C_URL="$MCP_B2C_URL_OVERRIDE"
fi

# Local defaults only — serve.py fails closed without a token (D7); deploys use real secrets.
# Locally the 3 services share ONE token; in deployment each service has its own.
export A2A_BEARER_TOKEN="${A2A_BEARER_TOKEN:-local-dev-token}"
export HOTEL_SEARCH_A2A_TOKEN="${HOTEL_SEARCH_A2A_TOKEN:-$A2A_BEARER_TOKEN}"
export FAQ_AGENT_A2A_TOKEN="${FAQ_AGENT_A2A_TOKEN:-$A2A_BEARER_TOKEN}"

# The concierge finds each leaf's agent card via *_CARD_URL, defaulting to the
# un-offset local-dev port (routing.py) — with PORT_OFFSET it must be told the
# shifted port explicitly, or it would keep dialing the other worktree's 8101/8102.
if [ "$PORT_OFFSET" != "0" ]; then
  export HOTEL_SEARCH_CARD_URL="${HOTEL_SEARCH_CARD_URL:-http://localhost:$((8101 + PORT_OFFSET))/.well-known/agent-card.json}"
  export FAQ_AGENT_CARD_URL="${FAQ_AGENT_CARD_URL:-http://localhost:$((8102 + PORT_OFFSET))/.well-known/agent-card.json}"
fi

UVICORN="$ROOT/.venv/bin/uvicorn"
[ -x "$UVICORN" ] || UVICORN="uvicorn"

# Base ports (PORT_OFFSET applied when actually binding/probing below).
SERVICES=(
  "hotel_search_agent:hotel_search_agent.serve:8101"
  "faq_agent:faq_agent.serve:8102"
  "b2c_concierge:b2c_concierge.serve:8100"
)

stop_all() {
  for spec in "${SERVICES[@]}"; do
    name="${spec%%:*}"
    pidfile="$RUN_DIR/$name.pid"
    if [ -f "$pidfile" ]; then
      pid="$(cat "$pidfile")"
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
        # Wait for the process to actually die: a draining uvicorn still holds
        # the port and would answer the readiness probe in place of its successor.
        for _ in $(seq 1 40); do
          kill -0 "$pid" 2>/dev/null || break
          sleep 0.25
        done
        echo "stopped $name (pid $pid)"
      fi
      rm -f "$pidfile"
    fi
  done
}

if [ "${1:-start}" = "stop" ]; then
  stop_all
  exit 0
fi

stop_all >/dev/null 2>&1 || true

for spec in "${SERVICES[@]}"; do
  name="${spec%%:*}"
  rest="${spec#*:}"
  module="${rest%:*}"
  port="$((${rest##*:} + PORT_OFFSET))"
  logfile="$RUN_DIR/$name.log"
  (
    cd "$ROOT/agents/$name"
    PORT="$port" nohup "$UVICORN" "$module:app" --port "$port" >"$logfile" 2>&1 &
    echo $! > "$RUN_DIR/$name.pid"
  )
  echo "starting $name on :$port (log: .run-logs/$name.log, pid: $(cat "$RUN_DIR/$name.pid"))"
done

# The agent card is the readiness probe (served without bearer by design).
for spec in "${SERVICES[@]}"; do
  name="${spec%%:*}"
  port="$((${spec##*:} + PORT_OFFSET))"
  ready=""
  for _ in $(seq 1 40); do
    if curl -sf "http://localhost:$port/.well-known/agent-card.json" >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 0.5
  done
  if [ -z "$ready" ]; then
    echo "ERROR: $name did not become ready on :$port — last log lines:" >&2
    tail -n 20 "$RUN_DIR/$name.log" >&2 || true
    stop_all
    exit 1
  fi
  echo "$name ready on :$port"
done

echo "all 3 services up — smoke: python scripts/smoke_e2e.py ; stop: bash scripts/run_local.sh stop"
