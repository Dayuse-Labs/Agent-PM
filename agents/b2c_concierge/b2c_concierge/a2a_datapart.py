"""A2A DataPart encode/decode over the ADK genai <-> A2A part conversion.

`RemoteA2aAgent` builds its outgoing A2A message purely from `ctx.session.events`
content parts (see `RemoteA2aAgent._construct_message_parts_from_session` —
there is no other injection point), converting each genai Part via
`convert_genai_part_to_a2a_part`. That converter turns a genai Part's
`inline_data` into a real A2A DataPart ONLY when it is wrapped in the
`<a2a_datapart_json>...</a2a_datapart_json>` tags with mime type text/plain
(google.adk.a2a.converters.part_converter) — the mechanism identified in S2/S3
handoff notes and used here to send `{query_params, profile_in}` to a leaf and
read back its `profile_delta`, without the spine ever emitting an extra
visible turn of text.
"""
from __future__ import annotations

from typing import Any

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import (
    A2A_DATA_PART_END_TAG,
    A2A_DATA_PART_START_TAG,
    A2A_DATA_PART_TEXT_MIME_TYPE,
)
from google.genai import types as genai_types


def encode_datapart(data: dict[str, Any]) -> genai_types.Part:
    """A genai Part that the outgoing A2A conversion turns into a real
    a2a DataPart(data=data) — append it to the outgoing message's parts
    (see agent.py's `_run_leaf`)."""
    payload = a2a_types.DataPart(data=data).model_dump_json(by_alias=True, exclude_none=True)
    return genai_types.Part(
        inline_data=genai_types.Blob(
            data=A2A_DATA_PART_START_TAG + payload.encode("utf-8") + A2A_DATA_PART_END_TAG,
            mime_type=A2A_DATA_PART_TEXT_MIME_TYPE,
        )
    )


def decode_datapart(part: genai_types.Part) -> dict[str, Any] | None:
    """The `data` dict of an A2A DataPart the ADK a2a->genai conversion
    wrapped into this Part's inline_data, or None if `part` isn't one."""
    blob = part.inline_data
    if not blob or blob.mime_type != A2A_DATA_PART_TEXT_MIME_TYPE or not blob.data:
        return None
    raw = blob.data
    if not (raw.startswith(A2A_DATA_PART_START_TAG) and raw.endswith(A2A_DATA_PART_END_TAG)):
        return None
    inner = raw[len(A2A_DATA_PART_START_TAG) : -len(A2A_DATA_PART_END_TAG)]
    try:
        parsed = a2a_types.DataPart.model_validate_json(inner)
    except ValueError:
        return None
    return parsed.data


def find_datapart(parts: list[genai_types.Part] | None) -> dict[str, Any] | None:
    """First decodable DataPart among `parts`, or None (e.g. the leaf hasn't
    been wired to emit one yet — an honest, silent no-op, never a crash)."""
    for part in parts or []:
        decoded = decode_datapart(part)
        if decoded is not None:
            return decoded
    return None
