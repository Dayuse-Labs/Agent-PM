"""Carry tool-authored FAQ scopes over A2A, without a lossy model summary.

Like the search leaf bridge, state is invocation-scoped and the outgoing
DataPart is built in code. No Redis, new tool, or additional model call.
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
_NOTE = "Official FAQ sources retrieved. Use their original scopes in FAQ EVIDENCE."


def capture_policy_evidence(tool: Any, args: dict[str, Any], tool_context: Any,
                            tool_response: Any) -> None:
    """Capture only successful MCP policy data, never the leaf's prose."""
    if getattr(tool, "name", None) != "get_faq_conditions":
        return
    if not isinstance(tool_response, dict) or tool_response.get("isError"):
        return
    payload = tool_response.get("structuredContent")
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
    if not callback_context.state.get(_STATE_EVIDENCE):
        return None
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=_NOTE)]))


def emit_policy_evidence(callback_context: Any) -> types.Content | None:
    evidence = callback_context.state.get(_STATE_EVIDENCE)
    if not evidence:
        return None
    # Deliberately no `results`: policy records are not hotel carousel cards.
    payload = a2a_types.DataPart(data={"faq_evidence": evidence}).model_dump_json(
        by_alias=True, exclude_none=True
    )
    part = types.Part(inline_data=types.Blob(
        data=A2A_DATA_PART_START_TAG + payload.encode("utf-8") + A2A_DATA_PART_END_TAG,
        mime_type=A2A_DATA_PART_TEXT_MIME_TYPE,
    ))
    return types.Content(role="model", parts=[types.Part(text=_NOTE), part])
