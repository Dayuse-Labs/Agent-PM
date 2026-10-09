"""Bind an owned named-hotel request to the existing read-only MCP lookup.

Only invocation-scoped state is used. Customer names remain separate from MCP
identities and dated offers, which the concierge still verifies afterwards.
"""
from __future__ import annotations

from typing import Any

from google.adk.models.llm_response import LlmResponse
from google.genai import types

from b2c_common.destination_request import DestinationRequest, destination_request
from hotel_search_agent.response_bridge import find_datapart, read_profile_in

_SENT = "temp:hotel_search_named_destination_sent"


def _owned(context: Any) -> DestinationRequest | None:
    content = getattr(context, "user_content", None)
    envelope = find_datapart(getattr(content, "parts", None)) or {}
    if (envelope.get("query_params") or {}).get("destination_authoritative") is not True:
        return None
    request = destination_request(read_profile_in(context).get("requested_destination"))
    return request if request and request.kind == "hotel" else None


def reset_named_destination(callback_context: Any) -> None:
    callback_context.state[_SENT] = False


def select_named_destination(callback_context: Any, llm_request: Any) -> LlmResponse | None:
    """Execute the validated request directly, without another model decision."""
    request = _owned(callback_context)
    if not request or callback_context.state.get(_SENT):
        return None
    callback_context.state[_SENT] = True
    args = {"name": request.query}
    if request.city:
        args["cityName"] = request.city
    return LlmResponse(content=types.Content(role="model", parts=[
        types.Part(function_call=types.FunctionCall(name="find_hotel_by_name", args=args)),
    ]))


def enforce_named_destination(tool: Any, args: dict[str, Any], tool_context: Any) -> dict | None:
    request = _owned(tool_context)
    if not request:
        return None
    if getattr(tool, "name", "") == "find_hotel_by_name":
        args["name"] = request.query
        if request.city:
            args["cityName"] = request.city
        else:
            args.pop("cityName", None)
    elif getattr(tool, "name", "") in {"geocode_location", "search_offers"}:
        return {"ok": False, "error": "named_destination_required",
                "diagnostics": {"requested_hotel": request.query,
                                "reason": "A named-hotel request cannot become a general city search."}}
    return None
