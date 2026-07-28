"""faq_agent — Dayuse B2C leaf agent (ADK + LiteLLM, portable).

FAQ / policy answers for the b2c-concierge orchestrator: given a question plus
an inbound profile, it calls the read-only MCP_B2C tool `get_faq_conditions`
over Streamable HTTP and returns the grounded conditions plus a profile delta
(see contract.py — the leaf is STATELESS, decision B3: no Redis, no session
store; all state travels in the A2A DataPart).

Separate leaf by PRODUCT decision D1 (the design review recommended inlining);
the latency parades are therefore non-negotiable here: 0-1 internal LLM call,
persistent (keep-alive) HTTP connections — the McpToolset holds one Streamable
HTTP session — and deployment co-located on the private network, so the extra
hop stays cheap.

Least privilege: `tool_filter` is an explicit allowlist of 1 of the 6 MCP_B2C
tools — search, details, compare and booking-link belong to other components
(hotel-search-agent, orchestrator inline tools) and must never be reachable
from here.

S3 wired dayuse_agent_common: build_model, day-1 metrics callbacks (stdout +
llm_metric_events, no-op without DATABASE_URL, never any message content) and
the tool budget. The agent NAME is the metrics `service` label — b2c_ prefixed
so B2C rows are distinguishable from fleet rows in the shared Postgres.
"""
from __future__ import annotations

import os

from b2c_common.observability import stamp_langfuse_session
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

# The only MCP_B2C tool this leaf may call, passed to McpToolset(tool_filter=...)
# so the other 5 server tools are never presented to the model.
ALLOWED_MCP_TOOLS = [
    "get_faq_conditions",
]

# D3: model via the lib's LiteLLM factory (reasoning kwargs included). B2C keeps
# its OWN departure default (iso-model comparison vs agent-usa): the lib's
# DEFAULT_MODEL is an OpenRouter slug and must never silently take over.
MODEL = build_model(os.environ.get("DAYUSE_MODEL", "gpt-4o-mini"))

# Hard cap on real tool calls per turn (one FAQ lookup; 2 leaves margin for a
# refined retry the model may attempt). Beyond it: deterministic short-circuit.
MAX_TOOL_CALLS = int(os.environ.get("FAQ_MAX_TOOL_CALLS", "2"))


def build_connection_params() -> StreamableHTTPConnectionParams:
    """Connection params for the MCP_B2C Streamable-HTTP server (read-only ES).

    MCP_B2C_AUTH_TOKEN travels as a standard RFC 6750 Bearer header (the
    server initially compared the raw header value and rejected the Bearer
    scheme; fixed server-side and deployed on 2026-07-17). It never enters
    the model context. Only send Authorization when a token is actually set:
    an empty value ("Bearer ") is an ILLEGAL header (h11 rejects the trailing
    whitespace) and would fail MCP session creation. .strip() guards a stray
    newline. Not validated eagerly — a bad URL/token fails loudly on the first
    tool call (connection is lazy, same pattern as hotel_search_agent).

    The 5 s default timeout is this leaf's OWNED budget for its MCP dependency
    (single-owner rule).
    """
    token = os.environ.get("MCP_B2C_AUTH_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return StreamableHTTPConnectionParams(
        # Local placeholder default — dev points at the staging MCP_B2C via .env
        # (staging is OK to develop against, FORBIDDEN for the shadow-run).
        url=os.environ.get("MCP_B2C_URL", "http://localhost:8099/mcp"),
        headers=headers,
        timeout=float(os.environ.get("FAQ_MCP_TIMEOUT_SECONDS", "5.0")),
    )


def build_mcp_toolset() -> McpToolset:
    return McpToolset(
        connection_params=build_connection_params(),
        tool_filter=ALLOWED_MCP_TOOLS,
    )


INSTRUCTION = """You are faq_agent, the Dayuse FAQ and policy leaf.

You receive ONE question as structured data: `query_params` (the FAQ intent —
the user's question about Dayuse conditions, policies, or how day-use works)
and `profile_in` (the caller-owned user profile snapshot). You are STATELESS:
you hold no session, no memory of previous turns — everything you know about
the user is in the request, and everything you learned must be returned in the
response.

How to act, frugally (at most ONE reasoning pass — no tool-call loops):
- Call get_faq_conditions with the question's topic to retrieve the official
  Dayuse conditions/policy content.
- Then return the outcome as structured data matching the response contract:
  `results` (the conditions/policy content as returned by the tool),
  `profile_delta` (only the NEW facts this turn taught about the user; empty
  if none), and `diagnostics` (what you called and why, plus any tool error —
  never invent an answer when a tool fails).

Never fabricate policies, conditions, deadlines, or amounts: only report what
the tool returned. If the tool returns nothing relevant or fails, say so in
diagnostics instead of guessing."""

# Metrics callbacks (fleet contract, booking_qa precedent). Deliberately NO
# switch_model_callback: B2C serves the public — a per-request MODEL: override
# must never be honored here.
root_agent = Agent(
    name="b2c_faq",
    model=MODEL,
    description=(
        "Answers Dayuse FAQ and policy questions (cancellation conditions, how day-use works) "
        "via the read-only MCP_B2C server; stateless — profile in/out through the A2A DataPart."
    ),
    instruction=INSTRUCTION,
    # Stateless leaf, enforced (latency audit 2026-07-28): current turn only —
    # same rationale and verification as b2c_hotel_search's include_contents.
    include_contents="none",
    tools=[build_mcp_toolset()],
    # stamp_langfuse_session mirrors the inbound A2A dayuse_trace_id as the
    # Langfuse session id (no-op unless tracing is enabled in serve.py).
    before_agent_callback=[stamp_langfuse_session],
    before_model_callback=[llm_timing_before],
    after_model_callback=[llm_timing_after],
    on_model_error_callback=llm_error_metric,
    # timing before budget: budget-stopped calls still get a t0 (the budget callback
    # is the only one returning non-None, which short-circuits the rest of the list).
    before_tool_callback=[tool_timing_before, make_tool_budget_callback(MAX_TOOL_CALLS)],
    after_tool_callback=[tool_timing_after],
    on_tool_error_callback=tool_error_metric,
)
