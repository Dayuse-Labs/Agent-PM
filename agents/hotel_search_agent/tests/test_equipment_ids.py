"""Offline unit tests for the code-owned amenity → equipment-ID hard filters.

No network, no LLM, no MCP. The injection tests use the REAL ADK `LlmRequest`
and genai `FunctionDeclaration` types (the exact objects the callback mutates);
the enforcement tests build `user_content` through the REAL ADK a2a→genai part
converter — the exact inbound hop that wraps the orchestrator's DataPart.
"""
from __future__ import annotations

import contextlib
import copy
import logging

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.adk.models.llm_request import LlmRequest
from google.genai import types as genai_types

from hotel_search_agent.equipment_ids import (
    EQUIPMENT_IDS,
    enforce_equipment_filters,
    equipment_ids_for,
    inject_amenities_declaration,
)
from hotel_search_agent.response_bridge import STATE_APPLIED_AMENITIES_KEY


class _Ctx:
    """Minimal stand-in for ADK ToolContext (dict-backed .state + user_content)."""

    def __init__(self, state=None, user_content=None):
        self.state = state if state is not None else {}
        self.user_content = user_content


class _Tool:
    def __init__(self, name):
        self.name = name


def _user_content_with_profile(amenities) -> genai_types.Content:
    """The inbound message as the leaf actually sees it: the orchestrator's
    `{query_params, profile_in}` a2a DataPart converted by the REAL ADK
    converter into the tag-envelope genai Part riding user_content."""
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": {"amenities": amenities}})
    )
    return genai_types.Content(
        role="user",
        parts=[
            genai_types.Part(text="je voudrais un hotel à miami avec une piscine"),
            convert_a2a_part_to_genai_part(datapart),
        ],
    )


# --- the table itself -------------------------------------------------------------------------
def test_pool_group_matches_the_server_or_group():
    # Exactly MCP_B2C's own HOTEL_POOL_EQUIPMENT_IDS (pool-equipment-ids.ts):
    # the only family the server OR-matches.
    assert EQUIPMENT_IDS["pool"] == (33, 34, 2982, 3000, 3001)


def test_table_matches_the_official_referential():
    # Spot-locks against src/shared/reference/hotel-equipment.json (2026-07-20).
    assert EQUIPMENT_IDS["spa"] == (35,)
    assert EQUIPMENT_IDS["gym"] == (38,)
    assert EQUIPMENT_IDS["jacuzzi"] == (41,)
    assert EQUIPMENT_IDS["sauna"] == (2951,)
    assert EQUIPMENT_IDS["restaurant"] == (14,)
    assert EQUIPMENT_IDS["breakfast"] == (2992,)
    assert EQUIPMENT_IDS["pet_friendly"] == (2956,)
    assert EQUIPMENT_IDS["shuttle"] == (2949,)


def test_and_trap_families_stay_unmapped():
    # parking (5 variant ids) and rooftop (bar vs pool ambiguity) cannot be
    # expressed with AND-matched ids — an unmapped key must degrade honestly.
    assert "parking" not in EQUIPMENT_IDS
    assert "rooftop" not in EQUIPMENT_IDS


def test_equipment_ids_for_flattens_ordered_and_deduped():
    assert equipment_ids_for(["pool", "spa"]) == [33, 34, 2982, 3000, 3001, 35]
    assert equipment_ids_for(["spa", "spa", "pool"]) == [35, 33, 34, 2982, 3000, 3001]


def test_equipment_ids_for_ignores_unknown_keys():
    assert equipment_ids_for(["parking", "rooftop", "nonsense"]) == []
    assert equipment_ids_for(None) == []
    assert equipment_ids_for([]) == []


# --- inject_amenities_declaration (before_model) ----------------------------------------------
def _llm_request(schema: dict | None) -> LlmRequest:
    decl = genai_types.FunctionDeclaration(name="search_offers")
    if schema is not None:
        decl.parameters_json_schema = schema
    other = genai_types.FunctionDeclaration(
        name="find_hotel_by_name", parameters_json_schema={"type": "object", "properties": {}}
    )
    return LlmRequest(
        config=genai_types.GenerateContentConfig(
            tools=[genai_types.Tool(function_declarations=[other, decl])]
        )
    )


_MCP_SCHEMA = {
    "type": "object",
    "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}},
    "required": ["lat", "lon", "date"],
    "additionalProperties": False,
}


def test_inject_adds_amenities_enum_to_search_offers_declaration():
    request = _llm_request(copy.deepcopy(_MCP_SCHEMA))
    assert inject_amenities_declaration(None, request) is None  # chain proceeds
    decl = request.config.tools[0].function_declarations[1]
    prop = decl.parameters_json_schema["properties"]["amenities"]
    assert prop["type"] == "array"
    assert prop["items"]["enum"] == list(EQUIPMENT_IDS)  # the closed world
    # the rest of the MCP schema is untouched
    assert decl.parameters_json_schema["required"] == ["lat", "lon", "date"]
    assert decl.parameters_json_schema["additionalProperties"] is False


def test_inject_never_mutates_the_source_schema_dict():
    # The declaration REFERENCES the McpTool's cached inputSchema — widening
    # must happen on a copy or the pristine schema is corrupted for good.
    source = copy.deepcopy(_MCP_SCHEMA)
    request = _llm_request(source)
    inject_amenities_declaration(None, request)
    assert source == _MCP_SCHEMA  # pristine


def test_inject_leaves_other_declarations_untouched():
    request = _llm_request(copy.deepcopy(_MCP_SCHEMA))
    inject_amenities_declaration(None, request)
    other = request.config.tools[0].function_declarations[0]
    assert "amenities" not in (other.parameters_json_schema or {}).get("properties", {})


def test_inject_noop_without_parameters_json_schema():
    # A future ADK flag flip (Schema objects instead of raw dicts) must degrade
    # to a no-op, never a crash — the profile-union leg keeps filtering.
    request = _llm_request(None)
    assert inject_amenities_declaration(None, request) is None
    assert request.config.tools[0].function_declarations[1].parameters_json_schema is None


def test_inject_is_idempotent_per_request():
    # Declarations are rebuilt every model call, but a double run on the same
    # request must not duplicate/corrupt anything.
    request = _llm_request(copy.deepcopy(_MCP_SCHEMA))
    inject_amenities_declaration(None, request)
    inject_amenities_declaration(None, request)
    decl = request.config.tools[0].function_declarations[1]
    assert decl.parameters_json_schema["properties"]["amenities"]["items"]["enum"] == list(
        EQUIPMENT_IDS
    )


# --- enforce_equipment_filters (before_tool) ---------------------------------------------------
def test_enforce_pops_virtual_amenities_and_sets_equipment_ids():
    ctx = _Ctx()
    args = {"lat": 25.76, "lon": -80.19, "date": "2026-07-21", "amenities": ["pool"]}
    assert enforce_equipment_filters(_Tool("search_offers"), args, ctx) is None
    assert "amenities" not in args  # the server's schema forbids it — never leaks
    assert args["hotelEquipmentIds"] == [33, 34, 2982, 3000, 3001]
    assert args["lat"] == 25.76  # the rest of the call is untouched


def test_enforce_drops_llm_hallucinated_equipment_ids():
    # THE original bug: a hallucinated id ([1]) hard-filters Miami to 0 offers.
    ctx = _Ctx()
    args = {"hotelEquipmentIds": [1], "roomEquipmentIds": [7]}
    enforce_equipment_filters(_Tool("search_offers"), args, ctx)
    assert "hotelEquipmentIds" not in args
    assert "roomEquipmentIds" not in args


def test_enforce_drops_unknown_amenity_values_silently():
    ctx = _Ctx()
    args = {"amenities": ["pool", "helipad", 42, None, "parking"]}
    enforce_equipment_filters(_Tool("search_offers"), args, ctx)
    assert args["hotelEquipmentIds"] == [33, 34, 2982, 3000, 3001]  # pool only
    assert ctx.state[STATE_APPLIED_AMENITIES_KEY] == ["pool"]


def test_enforce_normalizes_case_and_whitespace():
    ctx = _Ctx()
    args = {"amenities": ["  Pool ", "SPA"]}
    enforce_equipment_filters(_Tool("search_offers"), args, ctx)
    assert ctx.state[STATE_APPLIED_AMENITIES_KEY] == ["pool", "spa"]


def test_enforce_unions_with_profile_in_amenities():
    # Turn 2 "moins cher" carries no amenities arg — the accumulated profile
    # (turn 1 asked for a pool) must still filter. Profile keys come first.
    ctx = _Ctx(user_content=_user_content_with_profile(["pool"]))
    args = {"amenities": ["spa"]}
    enforce_equipment_filters(_Tool("search_offers"), args, ctx)
    assert ctx.state[STATE_APPLIED_AMENITIES_KEY] == ["pool", "spa"]
    assert args["hotelEquipmentIds"] == [33, 34, 2982, 3000, 3001, 35]


def test_enforce_profile_only_still_filters():
    ctx = _Ctx(user_content=_user_content_with_profile(["jacuzzi"]))
    args = {}
    enforce_equipment_filters(_Tool("search_offers"), args, ctx)
    assert args["hotelEquipmentIds"] == [41]


def test_enforce_missing_datapart_still_drops_llm_ids():
    # No DataPart on user_content (or none at all): honest no-op on the profile
    # leg, but the LLM-written ids are still dropped.
    for content in (None, genai_types.Content(role="user", parts=[genai_types.Part(text="hi")])):
        ctx = _Ctx(user_content=content)
        args = {"hotelEquipmentIds": [1]}
        enforce_equipment_filters(_Tool("search_offers"), args, ctx)
        assert "hotelEquipmentIds" not in args
        assert ctx.state[STATE_APPLIED_AMENITIES_KEY] == []


def test_enforce_no_amenities_leaves_no_filter_params_and_stashes_empty_list():
    ctx = _Ctx()
    args = {"lat": 1.0, "lon": 2.0, "date": "2026-07-21"}
    enforce_equipment_filters(_Tool("search_offers"), args, ctx)
    assert "hotelEquipmentIds" not in args
    assert "roomEquipmentIds" not in args
    assert ctx.state[STATE_APPLIED_AMENITIES_KEY] == []  # explicit — never stale


def test_enforce_pops_amenities_on_find_hotel_by_name():
    # The model was taught a virtual arg this tool's real schema forbids.
    ctx = _Ctx()
    args = {"name": "Villa", "amenities": ["pool"]}
    enforce_equipment_filters(_Tool("find_hotel_by_name"), args, ctx)
    assert "amenities" not in args
    assert "hotelEquipmentIds" not in args
    assert STATE_APPLIED_AMENITIES_KEY not in ctx.state  # not a search — no stash


def test_enforce_ignores_other_tools():
    ctx = _Ctx()
    args = {"location": "Miami"}
    enforce_equipment_filters(_Tool("geocode_location"), args, ctx)
    assert args == {"location": "Miami"}
    assert ctx.state == {}


# --- UX1: the retraction channel (`amenities_removed`) ----------------------------------------
def test_inject_adds_the_removal_param_with_the_same_closed_enum():
    # The model needs a channel to express a retraction — and it must be the
    # SAME closed world, or a removal key could never match a filter key.
    request = _llm_request(copy.deepcopy(_MCP_SCHEMA))
    inject_amenities_declaration(None, request)
    props = request.config.tools[0].function_declarations[1].parameters_json_schema["properties"]
    assert props["amenities_removed"]["items"]["enum"] == list(EQUIPMENT_IDS)
    assert props["amenities"]["items"]["enum"] == list(EQUIPMENT_IDS)


def test_enforce_subtracts_a_removed_key_from_the_profile_filter():
    # THE fix: turn 2 says "enlève le spa" with nothing else — the accumulated
    # profile filter must not come back.
    ctx = _Ctx(user_content=_user_content_with_profile(["spa"]))
    args = {"amenities_removed": ["spa"]}
    enforce_equipment_filters(_Tool("search_offers"), args, ctx)
    assert "amenities_removed" not in args  # virtual param, never reaches MCP
    assert "hotelEquipmentIds" not in args
    assert ctx.state[STATE_APPLIED_AMENITIES_KEY] == []


def test_enforce_subtracts_only_the_named_key():
    ctx = _Ctx(user_content=_user_content_with_profile(["pool", "spa"]))
    args = {"amenities_removed": ["spa"]}
    enforce_equipment_filters(_Tool("search_offers"), args, ctx)
    assert args["hotelEquipmentIds"] == [33, 34, 2982, 3000, 3001]
    assert ctx.state[STATE_APPLIED_AMENITIES_KEY] == ["pool"]


def test_enforce_removal_of_a_key_never_asked_for_is_a_no_op():
    ctx = _Ctx(user_content=_user_content_with_profile(["pool"]))
    args = {"amenities_removed": ["sauna"]}
    enforce_equipment_filters(_Tool("search_offers"), args, ctx)
    assert args["hotelEquipmentIds"] == [33, 34, 2982, 3000, 3001]
    assert ctx.state[STATE_APPLIED_AMENITIES_KEY] == ["pool"]


def test_enforce_removal_drops_unknown_values_like_the_request_leg():
    ctx = _Ctx(user_content=_user_content_with_profile(["pool"]))
    args = {"amenities_removed": ["helipad", 42, None, "  POOL "]}
    enforce_equipment_filters(_Tool("search_offers"), args, ctx)
    assert "hotelEquipmentIds" not in args  # the normalized "pool" still bit
    assert ctx.state[STATE_APPLIED_AMENITIES_KEY] == []


def test_a_key_in_both_fields_is_applied_not_removed():
    # gpt-4o-mini's negation-inversion trap (S10): on "je veux une piscine" it
    # can copy the key into BOTH fields. An explicit request THIS turn must
    # never be cancelled by a removal signal — the fail-safe direction is to
    # keep filtering, which the user can always retract next turn.
    ctx = _Ctx()
    args = {"amenities": ["pool"], "amenities_removed": ["pool"]}
    enforce_equipment_filters(_Tool("search_offers"), args, ctx)
    assert args["hotelEquipmentIds"] == [33, 34, 2982, 3000, 3001]
    assert ctx.state[STATE_APPLIED_AMENITIES_KEY] == ["pool"]


@contextlib.contextmanager
def _metric_lines():
    """The `dayuse.metrics` lines emitted inside the block. Read off the logger
    itself, not stdout: its handler is a StreamHandler bound to whatever
    `sys.stdout` was at import time and it does not propagate, so neither
    caplog nor capsys/capfd reliably sees it under pytest's own capture."""
    lines: list[str] = []

    class _Collect(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    logger = logging.getLogger("dayuse.metrics")
    handler = _Collect()
    logger.addHandler(handler)
    try:
        yield lines
    finally:
        logger.removeHandler(handler)


def test_a_collision_is_counted_in_a_content_free_metric():
    ctx = _Ctx()
    with _metric_lines() as lines:
        enforce_equipment_filters(
            _Tool("search_offers"), {"amenities": ["pool"], "amenities_removed": ["pool"]}, ctx
        )
    line = next(ln for ln in lines if "amenity_filter_conflict" in ln)
    assert "n_conflicts=1" in line
    assert "pool" not in line  # RGPD: counts only, never the keys


def test_no_conflict_metric_without_a_collision():
    ctx = _Ctx(user_content=_user_content_with_profile(["spa"]))
    with _metric_lines() as lines:
        enforce_equipment_filters(_Tool("search_offers"), {"amenities_removed": ["spa"]}, ctx)
    assert not [ln for ln in lines if "amenity_filter_conflict" in ln]


def test_enforce_pops_the_removal_param_on_find_hotel_by_name():
    ctx = _Ctx()
    args = {"name": "Villa", "amenities": ["pool"], "amenities_removed": ["spa"]}
    enforce_equipment_filters(_Tool("find_hotel_by_name"), args, ctx)
    assert args == {"name": "Villa"}


# --- the OBS3 guard --------------------------------------------------------------------------
def test_the_relaxation_guard_fires_when_a_key_is_actually_dropped():
    ctx = _Ctx(user_content=_user_content_with_profile(["spa"]))
    enforce_equipment_filters(_Tool("search_offers"), {"amenities_removed": ["spa"]}, ctx)
    assert ctx.state["temp:hotel_search_guards_fired"] == ["filter_relaxation_honored"]


def test_the_relaxation_guard_stays_silent_when_nothing_was_dropped():
    for args in ({"amenities": ["pool"]}, {"amenities_removed": ["sauna"]}, {}):
        ctx = _Ctx(user_content=_user_content_with_profile(["pool"]))
        enforce_equipment_filters(_Tool("search_offers"), dict(args), ctx)
        assert "temp:hotel_search_guards_fired" not in ctx.state


def test_the_relaxation_guard_does_not_fire_on_a_collision():
    # Nothing was relaxed: the key is still filtered on.
    ctx = _Ctx()
    enforce_equipment_filters(
        _Tool("search_offers"), {"amenities": ["pool"], "amenities_removed": ["pool"]}, ctx
    )
    assert "temp:hotel_search_guards_fired" not in ctx.state
