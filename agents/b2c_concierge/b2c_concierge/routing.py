"""Code-owned routing table of the b2c-concierge spine — no LLM decides control flow.

family → action:
- `leaf`     : one A2A leg via RemoteA2aAgent (D7 bearer + the 10 s budget the
               orchestrator owns, NO retry — see agent.py);
- `inline`   : an orchestrator-owned MCP tool — STUB until S4+ (inline_tools.py);
- `template` : deterministic code-owned answer, zero LLM (templates.py).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

LEAF_HOTEL_SEARCH = "hotel_search"
LEAF_FAQ = "faq"


@dataclass(frozen=True)
class Route:
    kind: str  # "leaf" | "inline" | "template"
    target: str  # leaf key, inline MCP tool name, or template key


ROUTES: dict[str, Route] = {
    "search": Route(kind="leaf", target=LEAF_HOTEL_SEARCH),
    "faq": Route(kind="leaf", target=LEAF_FAQ),
    "details": Route(kind="inline", target="get_hotel_details"),
    "compare": Route(kind="inline", target="compare_hotels"),
    "booking": Route(kind="inline", target="generate_booking_link"),
    "ack": Route(kind="template", target="ack"),
}

# Each leaf: (card-url env var, local-dev port, outbound-bearer env var).
# Local dev ports follow the AgentB2C range: 8100 concierge / 8101 search / 8102 faq.
LEAF_ENDPOINTS: dict[str, tuple[str, int, str]] = {
    LEAF_HOTEL_SEARCH: ("HOTEL_SEARCH_CARD_URL", 8101, "HOTEL_SEARCH_A2A_TOKEN"),
    LEAF_FAQ: ("FAQ_AGENT_CARD_URL", 8102, "FAQ_AGENT_A2A_TOKEN"),
}


def card_url(leaf: str) -> str:
    """Lazy card resolution: local dev ports by default, env overrides for deployments."""
    env_var, port, _ = LEAF_ENDPOINTS[leaf]
    return os.environ.get(env_var, f"http://localhost:{port}/.well-known/agent-card.json")


def bearer_token(leaf: str) -> str:
    """Outbound D7 bearer for one leaf (per-leaf secret in deployments; empty →
    the leg is sent unauthenticated and the fail-closed leaf 401s it, which
    degrades the turn honestly instead of silently skipping auth)."""
    _, _, env_var = LEAF_ENDPOINTS[leaf]
    return os.environ.get(env_var, "").strip()
