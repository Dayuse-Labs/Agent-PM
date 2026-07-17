"""hotel_search_agent — Dayuse B2C leaf agent (ADK + LiteLLM, portable).

Day-use hotel search for the b2c-concierge orchestrator: given structured query
params plus an inbound profile, it calls the read-only MCP_B2C tools
(`search_offers`, `find_hotel_by_name`) over Streamable HTTP and returns results
plus a profile delta (see contract.py — the leaf is STATELESS, decision B3: no
Redis, no session store; all state travels in the A2A DataPart).

Least privilege: `tool_filter` is an explicit allowlist of 2 of the 6 MCP_B2C
tools — the FAQ and booking-link tools belong to other components (faq-agent,
orchestrator inline tools) and must never be reachable from here.

S1 scope: functional skeleton only. Geo guards + Mapbox (with the circuit
breaker from resilience.py) arrive in S4; dayuse_agent_common (build_model,
metrics callbacks, tool budget) is wired in S3.
"""
from __future__ import annotations

import os

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams

# The only MCP_B2C tools this leaf may call, passed to McpToolset(tool_filter=...)
# so the other 4 server tools are never presented to the model.
ALLOWED_MCP_TOOLS = [
    "search_offers",
    "find_hotel_by_name",
]

# D3: model routed through LiteLLM only (DAYUSE_MODEL slug), never a direct
# cloud SDK. S3 replaces this with dayuse_agent_common.build_model().
MODEL = LiteLlm(model=os.environ.get("DAYUSE_MODEL", "gpt-4o-mini"))


def build_connection_params() -> StreamableHTTPConnectionParams:
    """Connection params for the MCP_B2C Streamable-HTTP server (read-only ES).

    MCP_B2C_AUTH_TOKEN travels in the Authorization header as the RAW token —
    the MCP_B2C server compares the full header value to its secret and
    REJECTS an RFC-style "Bearer <token>" (observed contract of the staging
    server, 2026-07-17: "Bearer x" → 401 Invalid token, raw x → 200). It never
    enters the model context. Only send Authorization when a token is actually
    set (an empty header is illegal and would fail MCP session creation);
    .strip() guards a stray newline. Not validated eagerly — a bad URL/token
    fails loudly on the first tool call (connection is lazy, same pattern as
    the fleet leaves).

    The 5 s default timeout is this leaf's OWNED budget for its MCP dependency
    (single-owner rule); the circuit breaker lands on this path in S4.
    """
    token = os.environ.get("MCP_B2C_AUTH_TOKEN", "").strip()
    headers = {"Authorization": token} if token else {}
    return StreamableHTTPConnectionParams(
        # Local placeholder default — dev points at the staging MCP_B2C via .env
        # (staging is OK to develop against, FORBIDDEN for the shadow-run).
        url=os.environ.get("MCP_B2C_URL", "http://localhost:8099/mcp"),
        headers=headers,
        timeout=float(os.environ.get("HOTEL_SEARCH_MCP_TIMEOUT_SECONDS", "5.0")),
    )


def build_mcp_toolset() -> McpToolset:
    return McpToolset(
        connection_params=build_connection_params(),
        tool_filter=ALLOWED_MCP_TOOLS,
    )


INSTRUCTION = """You are hotel_search_agent, the Dayuse day-use hotel search leaf.

You receive ONE search request as structured data: `query_params` (the search
intent — destination, dates, filters, or a hotel name) and `profile_in` (the
caller-owned user profile snapshot). You are STATELESS: you hold no session,
no memory of previous turns — everything you know about the user is in the
request, and everything you learned must be returned in the response.

How to act, frugally (at most ONE reasoning pass — no tool-call loops):
- A destination/area search → call search_offers with the query params.
- A specific hotel named by the user → call find_hotel_by_name.
- Keep the response SMALL: report AT MOST the top 5 results, each with only
  the fields a booking decision needs (name, address, rating, and per-offer
  price/hours/bedding). NEVER paste the raw tool payload — the caller has a
  strict latency budget. (The deterministic ≤5 ground-truth cap lands in S6.)
- Then return the outcome as structured data matching the response contract:
  `results` (the offers/hotels found, as returned by the tool), `profile_delta`
  (only the NEW facts this turn taught about the user, e.g. a city preference;
  empty if none), and `diagnostics` (what you called and why, plus any tool
  error — never invent results when a tool fails).

Never fabricate hotels, prices, or availability: only report what the tools
returned. If the request lacks enough to search, say so in diagnostics instead
of guessing."""

root_agent = Agent(
    name="hotel_search_agent",
    model=MODEL,
    description=(
        "Searches Dayuse day-use hotel offers (by destination or by hotel name) via the "
        "read-only MCP_B2C server; stateless — profile in/out through the A2A DataPart."
    ),
    instruction=INSTRUCTION,
    tools=[build_mcp_toolset()],
)
