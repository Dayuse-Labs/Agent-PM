"""MCP circuit breaker — wraps the 2 allowlisted MCP_B2C tool calls with the
`CircuitBreaker` from resilience.py (CLAUDE.md single-owner budget: MCP 5 s +
circuit-breaker, propriété de cette feuille).

A guard never re-runs a loop: once the breaker is open (repeated MCP_B2C
failures), further calls are short-circuited INSTANTLY with a clean
diagnostic dict — no remote hit, no exception, never a retry storm against a
dead dependency. Wired as ADK `before_tool_callback` / `after_tool_callback`
/ `on_tool_error_callback`, same mechanism as dayuse_agent_common's tool
budget and metrics callbacks (see agent.py).
"""
from __future__ import annotations

from typing import Any

from b2c_common.observability import mark_level
from dayuse_agent_common.metrics import tool_timing_after
from hotel_search_agent.resilience import CircuitBreaker

# The 2 tools this breaker owns — the same allowlist as ALLOWED_MCP_TOOLS in
# agent.py (kept independent here so this module has no import-time
# dependency on agent.py).
MCP_TOOL_NAMES = frozenset({"search_offers", "find_hotel_by_name"})

breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0)


def _degraded_response(tool_name: str) -> dict:
    # The `reason` enters the MODEL's context and can be echoed to the customer
    # on a degraded turn (audit CX 2026-07-24, F3) — customer-neutral wording
    # only, never internal jargon (no "MCP_B2C", no "circuit").
    return {
        "ok": False,
        "error": "mcp_circuit_open",
        "diagnostics": {
            "tool": tool_name,
            "reason": "the hotel search backend is temporarily unavailable — tell the user "
            "honestly that the search cannot run right now and to retry in a moment",
        },
    }


def _business_error_envelope(tool_response: dict) -> dict | None:
    """MCP_B2C's typed error envelope, when the response carries one.

    Since 2026-07-29 every MCP_B2C error answers with
    `structuredContent.error = {kind, message, retryable, ...}`. `retryable:
    False` means the server ANSWERED correctly and the request is what needs
    refining (`HotelNotFoundError`, `AmbiguousHotelError`,
    `MissingMandatoryCriterionError`, ...). An older server sends no envelope →
    None, and the caller keeps its previous conservative behaviour.
    """
    payload = tool_response.get("structuredContent")
    if not isinstance(payload, dict):
        return None
    envelope = payload.get("error")
    if isinstance(envelope, dict) and envelope.get("retryable") is False:
        return envelope
    return None


# The MCP SDK's own schema check ("MCP error -32602: Input validation error:
# Invalid arguments for tool search_offers: Unrecognized key(s) in object:
# 'currency'") carries no typed envelope. The server answered: the REQUEST was
# wrong (QA trace 9bc5feb6, "affiche en dollars"), not the dependency.
_INVALID_PARAMS_MARKERS = ("-32602", "Input validation error")


def _error_text(tool_response: dict) -> str:
    content = tool_response.get("content")
    if isinstance(content, list):
        return " ".join(
            str(item.get("text", "")) for item in content if isinstance(item, dict)
        )
    return ""


def classify_mcp_error(tool_response: Any) -> str | None:
    """None for a response that is not an error, else:
    - "not_found": `find_hotel_by_name` found no hotel by that name;
    - "rejected": the server refused this request (typed business error or
      invalid arguments) — retrying the same call cannot help;
    - "failed": the dependency itself failed."""
    if not isinstance(tool_response, dict):
        return None
    envelope = _business_error_envelope(tool_response)
    if envelope is not None:
        return "not_found" if envelope.get("kind") == "HotelNotFoundError" else "rejected"
    if tool_response.get("isError") and any(
        marker in _error_text(tool_response) for marker in _INVALID_PARAMS_MARKERS
    ):
        return "rejected"
    if _is_tool_failure(tool_response):
        return "failed"
    return None


def _is_tool_failure(tool_response: Any) -> bool:
    """Classify a completed (non-raising) MCP tool response as success/failure.

    ADK's MCP graceful error handling (default ON) turns transport/tool
    exceptions into error dicts rather than raising, so this is the PRIMARY
    failure detector — `mcp_circuit_on_error` is belt-and-suspenders for a
    genuinely raised exception.

    A typed BUSINESS error is not a dependency failure: three "no hotel by that
    name" answers in a row used to open the breaker, and every search for the
    next 30 s was then short-circuited with "the backend is unavailable" — a
    fake outage caused by a healthy backend answering correctly.
    """
    if not isinstance(tool_response, dict):
        return False
    error_text = str(tool_response.get("error", "") or "")
    if error_text.startswith("TOOL BUDGET"):
        return False  # control flow (tool_budget stop), not an MCP failure
    if _business_error_envelope(tool_response) is not None:
        return False
    if tool_response.get("isError") and any(
        marker in _error_text(tool_response) for marker in _INVALID_PARAMS_MARKERS
    ):
        return False
    if tool_response.get("isError"):
        return True
    if error_text:
        return True
    payload = tool_response.get("structuredContent")
    if isinstance(payload, dict) and payload.get("ok") is False:
        return True
    return tool_response.get("ok") is False


# ADK 2.4 runs every after_tool_callback even when a before_tool_callback
# short-circuited the call (flows/llm_flows/functions.py, steps 4-6), so a
# local refusal ({"ok": False, ...}) reached the breaker and the metric as if
# MCP had failed. The breaker is module-global: three refusals from anyone gave
# every user 30 s of "the search is unavailable". Instead of a list of local
# error strings to keep in sync, the chain itself says whether the call left:
# FIRST it is marked pending, and only a real dispatch clears the mark — the
# end of the chain (ADK then runs the tool) or a callback that calls
# `tool.run_async` itself. A context the chain never saw (no mark) is observed
# as before.
_DISPATCHED_ATTR = "_b2c_mcp_dispatched"


def mcp_call_pending(tool: Any, args: dict, tool_context: Any) -> None:
    """before_tool_callback, before any guard that may refuse the call."""
    if tool.name in MCP_TOOL_NAMES:
        setattr(tool_context, _DISPATCHED_ATTR, False)
    return None


def mark_mcp_dispatched(tool_context: Any) -> None:
    """Called right before a real MCP request leaves this leaf."""
    setattr(tool_context, _DISPATCHED_ATTR, True)


def mcp_call_dispatched(tool: Any, args: dict, tool_context: Any) -> None:
    """before_tool_callback, LAST: nothing refused, so ADK runs the tool."""
    if tool.name in MCP_TOOL_NAMES:
        mark_mcp_dispatched(tool_context)
    return None


def _locally_refused(tool: Any, tool_context: Any) -> bool:
    return tool.name in MCP_TOOL_NAMES and getattr(tool_context, _DISPATCHED_ATTR, True) is False


def mcp_tool_metric_after(
    tool: Any, args: dict, tool_context: Any, tool_response: Any
) -> dict | None:
    """after_tool_callback: the fleet's tool_call row, minus fake errors.

    A local refusal never reached MCP: it is metered like the fleet's own
    budget stop (control flow, status=ok), never as `tool_returned_error`. The
    budget stop keeps its response so `budget_stopped=true` still shows."""
    if _locally_refused(tool, tool_context) and not str(
        (tool_response or {}).get("error", "") if isinstance(tool_response, dict) else ""
    ).startswith("TOOL BUDGET"):
        tool_response = None
    return tool_timing_after(tool, args, tool_context, tool_response)


def mcp_circuit_before_tool(tool: Any, args: dict, tool_context: Any) -> dict | None:
    """before_tool_callback: refuse the call instantly while the breaker is open."""
    if tool.name not in MCP_TOOL_NAMES:
        return None
    if not breaker.allow():
        mark_level("ERROR", status_message="mcp_circuit_open")
        return _degraded_response(tool.name)
    return None


def mcp_circuit_after_tool(
    tool: Any, args: dict, tool_context: Any, tool_response: Any
) -> dict | None:
    """after_tool_callback: feed the breaker from the real call's outcome.

    Never rewrites the response — this only observes; the model still sees
    whatever the tool actually returned.
    """
    if tool.name not in MCP_TOOL_NAMES or _locally_refused(tool, tool_context):
        return None
    if _is_tool_failure(tool_response):
        breaker.record_failure()
    else:
        breaker.record_success()
    return None


def mcp_circuit_on_error(
    tool: Any, args: dict, tool_context: Any, error: Exception
) -> dict | None:
    """on_tool_error_callback: a genuinely raised exception also counts as a
    breaker failure, and is swallowed into a clean diagnostic dict — the
    leaf must never crash on an MCP outage, it degrades honestly instead."""
    if tool.name not in MCP_TOOL_NAMES:
        return None
    breaker.record_failure()
    mark_level("ERROR", status_message="mcp_dependency_failed")
    return _degraded_response(tool.name)
