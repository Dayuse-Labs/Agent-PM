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

from hotel_search_agent.resilience import CircuitBreaker

# The 2 tools this breaker owns — the same allowlist as ALLOWED_MCP_TOOLS in
# agent.py (kept independent here so this module has no import-time
# dependency on agent.py).
MCP_TOOL_NAMES = frozenset({"search_offers", "find_hotel_by_name"})

breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0)


def _degraded_response(tool_name: str) -> dict:
    return {
        "ok": False,
        "error": "mcp_circuit_open",
        "diagnostics": {
            "tool": tool_name,
            "reason": "MCP_B2C unavailable — circuit open after repeated failures",
        },
    }


def _is_tool_failure(tool_response: Any) -> bool:
    """Classify a completed (non-raising) MCP tool response as success/failure.

    ADK's MCP graceful error handling (default ON) turns transport/tool
    exceptions into error dicts rather than raising, so this is the PRIMARY
    failure detector — `mcp_circuit_on_error` is belt-and-suspenders for a
    genuinely raised exception.
    """
    if not isinstance(tool_response, dict):
        return False
    error_text = str(tool_response.get("error", "") or "")
    if error_text.startswith("TOOL BUDGET"):
        return False  # control flow (tool_budget stop), not an MCP failure
    if tool_response.get("isError"):
        return True
    if error_text:
        return True
    payload = tool_response.get("structuredContent")
    if isinstance(payload, dict) and payload.get("ok") is False:
        return True
    return tool_response.get("ok") is False


def mcp_circuit_before_tool(tool: Any, args: dict, tool_context: Any) -> dict | None:
    """before_tool_callback: refuse the call instantly while the breaker is open."""
    if tool.name not in MCP_TOOL_NAMES:
        return None
    if not breaker.allow():
        return _degraded_response(tool.name)
    return None


def mcp_circuit_after_tool(
    tool: Any, args: dict, tool_context: Any, tool_response: Any
) -> dict | None:
    """after_tool_callback: feed the breaker from the real call's outcome.

    Never rewrites the response — this only observes; the model still sees
    whatever the tool actually returned.
    """
    if tool.name not in MCP_TOOL_NAMES:
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
    return _degraded_response(tool.name)
