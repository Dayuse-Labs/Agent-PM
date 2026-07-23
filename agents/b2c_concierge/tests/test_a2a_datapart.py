"""Round-trip tests for the A2A DataPart envelope: encode -> the same shape
the ADK a2a<->genai converters produce -> decode."""
from __future__ import annotations

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import (
    convert_a2a_part_to_genai_part,
    convert_genai_part_to_a2a_part,
)
from google.genai import types as genai_types

from b2c_concierge.a2a_datapart import decode_datapart, encode_datapart, find_datapart


class TestEncodeDecodeRoundTrip:
    def test_decodes_its_own_encoding(self):
        payload = {"query_params": {"city": "Paris"}, "profile_in": {"budget_max": 150}}
        part = encode_datapart(payload)
        assert decode_datapart(part) == payload

    def test_non_datapart_part_decodes_to_none(self):
        assert decode_datapart(genai_types.Part(text="hello")) is None

    def test_find_datapart_skips_text_parts(self):
        payload = {"profile_delta": {"city": "Lyon"}}
        parts = [genai_types.Part(text="some leaf text"), encode_datapart(payload)]
        assert find_datapart(parts) == payload

    def test_find_datapart_none_when_absent(self):
        assert find_datapart([genai_types.Part(text="just text")]) is None
        assert find_datapart(None) is None
        assert find_datapart([]) is None

    def test_find_datapart_prefers_the_last_match_over_the_first(self):
        # S-G5 root-cause fix (live-verified 2026-07-23): a parts list carrying
        # SEVERAL turns' DataParts (an accumulating history) must yield the
        # MOST RECENT one, never the first/stale one.
        stale = {"profile_delta": {"city": "Lyon"}}
        fresh = {"profile_delta": {"city": "Paris"}}
        parts = [encode_datapart(stale), genai_types.Part(text="text in between"), encode_datapart(fresh)]
        assert find_datapart(parts) == fresh


class TestRoundTripThroughRealA2aConverters:
    """The encoded Part must survive an actual genai -> A2A -> genai hop
    (the real conversion RemoteA2aAgent performs on the wire)."""

    def test_survives_the_real_genai_to_a2a_to_genai_conversion(self):
        payload = {"query_params": {"city": "Paris"}, "profile_in": {"language": "fr"}}
        outgoing = encode_datapart(payload)

        a2a_part = convert_genai_part_to_a2a_part(outgoing)
        assert isinstance(a2a_part.root, a2a_types.DataPart)
        assert a2a_part.root.data == payload

        incoming = convert_a2a_part_to_genai_part(a2a_part)
        assert decode_datapart(incoming) == payload
