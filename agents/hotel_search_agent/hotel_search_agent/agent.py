"""hotel_search_agent — Dayuse B2C leaf agent (ADK + LiteLLM, portable).

Day-use hotel search for the b2c-concierge orchestrator: given structured query
params plus an inbound profile, it calls the read-only MCP_B2C tools
(`search_offers`, `find_hotel_by_name`) over Streamable HTTP and returns results
plus a profile delta (see contract.py — the leaf is STATELESS, decision B3: no
Redis, no session store; all state travels in the A2A DataPart).

Least privilege: `tool_filter` is an explicit allowlist of 2 of the 6 MCP_B2C
tools — the FAQ and booking-link tools belong to other components (faq-agent,
orchestrator inline tools) and must never be reachable from here.

S4 wired the geo guards + a real Mapbox client (geo_guards.py, mapbox_client.py,
geocode_tool.py) — `geocode_location` is a code-owned FunctionTool the model
calls before `search_offers` so `search_offers` gets real, guard-validated
lat/lon instead of the model's own world knowledge (MCP_B2C does no
geocoding server-side). The MCP circuit breaker (resilience.py, wired via
mcp_guard.py) degrades the 2 MCP tools honestly when MCP_B2C is down — a
clean diagnostic dict, never an exception.

S3 wired dayuse_agent_common: build_model, day-1 metrics callbacks (stdout +
llm_metric_events, no-op without DATABASE_URL, never any message content) and
the tool budget. The agent NAME is the metrics `service` label — b2c_ prefixed
so B2C rows are distinguishable from fleet rows in the shared Postgres.
"""
from __future__ import annotations

import os
from datetime import date
from typing import Any

from dayuse_agent_common import (
    build_model,
    llm_error_metric,
    llm_timing_after,
    llm_timing_before,
    make_tool_budget_callback,
    tool_error_metric,
    tool_timing_after,
    tool_timing_before,
)
from google.adk.agents import Agent
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams

from hotel_search_agent.geocode_tool import geocode_location
from hotel_search_agent.mcp_guard import (
    mcp_circuit_after_tool,
    mcp_circuit_before_tool,
    mcp_circuit_on_error,
)
from hotel_search_agent.response_bridge import (
    capture_after_tool,
    emit_search_datapart,
    skip_final_generation,
)

# The only MCP_B2C tools this leaf may call, passed to McpToolset(tool_filter=...)
# so the other 4 server tools are never presented to the model.
ALLOWED_MCP_TOOLS = [
    "search_offers",
    "find_hotel_by_name",
]

# D3: model via the lib's LiteLLM factory (reasoning kwargs included). B2C keeps
# its OWN departure default (iso-model comparison vs agent-usa): the lib's
# DEFAULT_MODEL is an OpenRouter slug and must never silently take over.
MODEL = build_model(os.environ.get("DAYUSE_MODEL", "gpt-4o-mini"))

# Hard cap on real tool calls per turn (the instruction says one reasoning pass;
# geocode_location + search_offers covers a destination search, find_hotel_by_name
# covers the named-hotel edge in 1). Beyond it the call is short-circuited
# deterministically — never a loop.
MAX_TOOL_CALLS = int(os.environ.get("HOTEL_SEARCH_MAX_TOOL_CALLS", "2"))


def build_connection_params() -> StreamableHTTPConnectionParams:
    """Connection params for the MCP_B2C Streamable-HTTP server (read-only ES).

    MCP_B2C_AUTH_TOKEN travels as a standard RFC 6750 Bearer header (the
    server initially compared the raw header value and rejected the Bearer
    scheme; fixed server-side and deployed on 2026-07-17). It never enters
    the model context. Only send Authorization when a token is actually set:
    an empty value ("Bearer ") is an ILLEGAL header (h11 rejects the trailing
    whitespace) and would fail MCP session creation. .strip() guards a stray
    newline. Not validated eagerly — a bad URL/token fails loudly on the first
    tool call (connection is lazy, same pattern as the fleet leaves).

    The 5 s default timeout is this leaf's OWNED budget for its MCP dependency
    (single-owner rule); the circuit breaker lands on this path in S4.
    """
    token = os.environ.get("MCP_B2C_AUTH_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
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
- A destination/area search → FIRST call geocode_location (pass the city/zone/
  metro/country_code you extracted, the raw user message, and any state/city
  context you saw in profile_in as profile_state_context/profile_location_hint).
  It is a deterministic, guarded tool — never geocode a destination yourself.
  If it returns ok=False, DO NOT call search_offers: relay its diagnostics
  honestly instead (never invent coordinates or guess a nearby city).
  If it returns ok=True, call search_offers with its latitude/longitude plus
  the rest of the query params, and fold its profile_delta into your own.
- A FOLLOW-UP that only changes the date/budget/filters with NO new destination
  (e.g. "for the 28th instead", "cheaper", "earlier") → reuse profile_in.city as
  the destination and run a fresh search with the new constraint. Do not ask the
  user to repeat the city they already gave.
- A specific hotel named by the user → call find_hotel_by_name directly (no
  geocoding needed).
- On a SUCCESSFUL search, reply with a SHORT one-line outcome in plain language
  (how many day-use offers, and in which city). Do NOT format a detailed hotel
  list and NEVER paste the raw tool payload — the structured top-5 results are
  attached to the response for the caller AUTOMATICALLY, and the caller has a
  strict latency budget, so keep this text to a single sentence.
- On FAILURE (geocode ok=False, no offers, or MCP_B2C degraded), do NOT call
  further tools: explain honestly in one or two sentences what happened.

Never fabricate hotels, prices, availability, or coordinates: only report what
the tools returned. If the request lacks enough to search, say so plainly
instead of guessing."""


def inject_today_before_model(callback_context: Any, llm_request: Any) -> None:
    """Injects TODAY into the model's context on every LLM call. The model has no
    clock: without this it cannot turn "demain"/"tomorrow" into a real date and
    sends search_offers a wrong/hallucinated date → zero offers (the S4 date-
    anchoring gap — the smoke only ever pinned an absolute date, so this stayed
    hidden). MCP_B2C does no date resolution server-side, exactly like geocoding.
    Done here (not via a callable instruction) because the A2A card builder
    regex-scans `instruction` and rejects a callable."""
    today = date.today()
    llm_request.append_instructions(
        [
            f"TODAY is {today.isoformat()} ({today.strftime('%A')}) — you have no other clock. "
            "Resolve EVERY relative date against it before calling search_offers: "
            "'today'/'aujourd'hui' = TODAY, 'tomorrow'/'demain' = TODAY + 1 day, "
            "'après-demain' = TODAY + 2 days, a named weekday = its NEXT occurrence. ALWAYS "
            "pass search_offers an absolute date as YYYY-MM-DD; never a past date, never guess "
            "the year."
        ]
    )
    return None

# Metrics callbacks (fleet contract, booking_qa precedent). Deliberately NO
# switch_model_callback: B2C serves the public — a per-request MODEL: override
# must never be honored here.
root_agent = Agent(
    name="b2c_hotel_search",
    model=MODEL,
    description=(
        "Searches Dayuse day-use hotel offers (by destination or by hotel name) via the "
        "read-only MCP_B2C server; stateless — profile in/out through the A2A DataPart."
    ),
    instruction=INSTRUCTION,
    tools=[build_mcp_toolset(), geocode_location],
    # skip_final_generation is FIRST: once the search tool has run, it short-circuits
    # the model's wasted final-prose call (emit_search_datapart overwrites that prose
    # and the orchestrator re-synthesizes anyway) — 3 → 2 internal LLM calls. Being
    # first means a skipped call never stamps an orphaned llm_timing_before timer
    # (the short-circuit returns before after_model_callback/llm_timing_after runs).
    # inject_today_before_model gives the (clockless) model TODAY so it resolves
    # "demain"/"tomorrow"/weekdays into an absolute date for search_offers.
    before_model_callback=[skip_final_generation, llm_timing_before, inject_today_before_model],
    after_model_callback=[llm_timing_after],
    on_model_error_callback=llm_error_metric,
    # Order matters: timing stamps t0 first; the budget callback short-circuits
    # beyond MAX_TOOL_CALLS; the MCP circuit guard short-circuits the 2 MCP
    # tools while the breaker is open. First non-None wins (ADK semantics).
    before_tool_callback=[
        tool_timing_before,
        make_tool_budget_callback(MAX_TOOL_CALLS),
        mcp_circuit_before_tool,
    ],
    # capture_after_tool is LAST: it may return a truncated payload (which breaks
    # the after-tool chain), so it must never run before mcp_circuit_after_tool
    # observes the real tool outcome. It stashes normalized results + the geocode
    # profile_delta and shrinks the ~24k-token search_offers payload the model
    # ingests (response_bridge.py).
    after_tool_callback=[tool_timing_after, mcp_circuit_after_tool, capture_after_tool],
    on_tool_error_callback=[tool_error_metric, mcp_circuit_on_error],
    # Emits the structured {results, profile_delta} A2A DataPart the orchestrator
    # decodes — the leaf's prose answer alone left `hotels` empty (S4/S5/S6 gap).
    after_agent_callback=[emit_search_datapart],
)
