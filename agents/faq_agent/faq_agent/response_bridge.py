"""Carry tool-authored FAQ scopes over A2A, without a lossy model summary.

Like the search leaf bridge, state is invocation-scoped and the outgoing
DataPart is built in code. No Redis or new tool. Oversized all-topic results
allow one narrowed lookup; other failures terminate without a model loop.
"""
from __future__ import annotations

import json
from typing import Any

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import (
    A2A_DATA_PART_END_TAG,
    A2A_DATA_PART_START_TAG,
    A2A_DATA_PART_TEXT_MIME_TYPE,
)
from google.adk.models.llm_response import LlmResponse
from google.genai import types

_STATE_EVIDENCE = "temp:faq_policy_evidence"
_STATE_ATTEMPT = "temp:faq_policy_attempt"
_STATE_NARROW = "temp:faq_narrow_request"
_MISSING = "No verified FAQ source is available for this turn. Explain that the policy could not be checked; never infer conditions, overnight eligibility, fees or refund promises from memory."
_NOTE = "Official FAQ sources retrieved. Use their original scopes in FAQ EVIDENCE."


def mark_policy_attempt(tool: Any, args: dict[str, Any], tool_context: Any) -> dict | None:
    """Admit only one narrower recovery after a structured oversized result."""
    if getattr(tool, "name", None) != "get_faq_conditions":
        return None
    state = tool_context.state
    state[_STATE_ATTEMPT] = int(state.get(_STATE_ATTEMPT) or 0) + 1
    original = state.get(_STATE_NARROW)
    state[_STATE_NARROW] = None
    if isinstance(original, dict):
        topic = args.get("topic")
        same_scope = {k: v for k, v in args.items() if k != "topic"} == {
            k: v for k, v in original.items() if k != "topic"}
        if not same_scope or not isinstance(topic, str) or not topic or topic == "all":
            return {"isError": True, "error": {
                "kind": "InvalidPolicyNarrowing",
                "message": "Recovery must narrow topic and preserve the original market/hotel scope."}}
    return None


def capture_policy_evidence(tool: Any, args: dict[str, Any], tool_context: Any,
                            tool_response: Any) -> None:
    """Capture only successful MCP policy data, never the leaf's prose."""
    if getattr(tool, "name", None) != "get_faq_conditions":
        return
    if not isinstance(tool_response, dict):
        return
    payload = tool_response.get("structuredContent")
    if tool_response.get("isError"):
        error = payload.get("error") if isinstance(payload, dict) else None
        if (isinstance(error, dict) and error.get("kind") == "ResultTooLargeError"
                and args.get("topic") == "all"
                and tool_context.state.get(_STATE_ATTEMPT) == 1):
            # Retrying unchanged cannot help. The next attempt must narrow the
            # topic; mark_policy_attempt prevents repeating all or changing scope.
            tool_context.state[_STATE_NARROW] = dict(args)
        return
    if not isinstance(payload, dict):
        for block in tool_response.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            try:
                payload = json.loads(block.get("text", ""))
            except (ValueError, TypeError):
                continue
            if isinstance(payload, dict):
                break
    if not isinstance(payload, dict) or payload.get("error"):
        return
    if not (isinstance(payload.get("sections"), dict)
            or isinstance(payload.get("generalFaq"), list)):
        return
    evidence = list(tool_context.state.get(_STATE_EVIDENCE) or [])
    evidence.append(payload)
    tool_context.state[_STATE_EVIDENCE] = evidence[-2:]


def skip_policy_summary(callback_context: Any, llm_request: Any) -> LlmResponse | None:
    """Once the tool returned evidence, synthesis owns the only interpretation."""
    if callback_context.state.get(_STATE_EVIDENCE):
        note = _NOTE
    elif callback_context.state.get(_STATE_NARROW):
        if llm_request is not None:
            llm_request.append_instructions([
                "The all-topic FAQ result exceeded the source size limit. Make ONE "
                "get_faq_conditions call with a specific topic relevant to the user's "
                "question. Keep the same market and hotel arguments. Do not repeat all "
                "or answer from memory; if this fails, the source remains unverified."])
        return None
    elif callback_context.state.get(_STATE_ATTEMPT):
        note = _MISSING
    else:
        return None
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=note)]))


def emit_policy_evidence(callback_context: Any) -> types.Content | None:
    evidence = callback_context.state.get(_STATE_EVIDENCE) or []
    note = _NOTE if evidence else _MISSING
    # Deliberately no `results`: policy records are not hotel carousel cards.
    payload = a2a_types.DataPart(data={"faq_evidence": evidence, "faq_diagnostics": {"source_verified": bool(evidence)}}).model_dump_json(
        by_alias=True, exclude_none=True
    )
    part = types.Part(inline_data=types.Blob(
        data=A2A_DATA_PART_START_TAG + payload.encode("utf-8") + A2A_DATA_PART_END_TAG,
        mime_type=A2A_DATA_PART_TEXT_MIME_TYPE,
    ))
    return types.Content(role="model", parts=[types.Part(text=note), part])
