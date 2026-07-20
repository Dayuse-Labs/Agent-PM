"""equipment_ids.py — code-owned amenity → MCP_B2C equipment-ID hard filters.

The MCP `search_offers` tool has NO text amenity parameter — only
`hotelEquipmentIds`/`roomEquipmentIds`, arrays of integer equipment IDs used as
HARD filters (`additionalProperties: false`). Left to itself the model
hallucinates an ID ("piscine" → `[1]`), and a hard filter on a nonexistent ID
returns zero offers while looking like a perfectly healthy search
(live-reproduced 2026-07-20: Miami `[33]` → 44 hotels, `[1]` → 0).

Split of responsibility (spine invariant — the LLM never writes a filter value):
- `inject_amenities_declaration` (before_model) widens the `search_offers`
  declaration THE MODEL SEES with a virtual `amenities` param whose enum is
  closed to `EQUIPMENT_IDS`' keys — the model only ever extracts INTENT.
- `enforce_equipment_filters` (before_tool) pops that virtual param before the
  MCP server (whose real schema forbids it) can see it, validates every key
  against the table, unions with the accumulated `profile_in.amenities` from
  the request DataPart, and re-writes `hotelEquipmentIds` deterministically —
  after unconditionally dropping whatever the model put there.

ID provenance — MCP_B2C's own referential (read 2026-07-20):
`src/shared/reference/hotel-equipment.json` + `pool-equipment-ids.ts`.
Server filter semantics: pool ids are OR-grouped (any pool satisfies), every
other id is AND-required individually. That asymmetry decides the table:
- "pool" maps to exactly the server's `HOTEL_POOL_EQUIPMENT_IDS` OR-group.
- Multi-variant non-pool families CANNOT express "any of": parking (22 valet /
  23 free / 24 paid / 25 garage / 2948 close-by) and rooftop (2981 bar vs 2982
  pool — and 2982 is already reachable through the pool group) stay UNMAPPED:
  the search runs unfiltered and the concierge's amenity claim guard hedges,
  which is honest. Sauna keeps only the modern 2951 (40 legacy combined and
  2952 Hammam would AND), shuttle only 2949 (2950 fees / 2980 local would AND).
- Room-level ids (`roomEquipmentIds`, pool group [2966, 2968]) are out of v1:
  always popped, never set.
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from hotel_search_agent.response_bridge import STATE_APPLIED_AMENITIES_KEY, find_datapart

EQUIPMENT_IDS: dict[str, tuple[int, ...]] = {
    "pool": (33, 34, 2982, 3000, 3001),  # outdoor, indoor, rooftop pool, pool bar, pool
    "spa": (35,),
    "gym": (38,),  # Fitness room; 37 "Centre de remise en forme" is a legacy duplicate
    "jacuzzi": (41,),  # "Hot tub", slug "jacuzzi"
    "sauna": (2951,),
    "restaurant": (14,),
    "breakfast": (2992,),  # Breakfast Area
    "pet_friendly": (2956,),  # "Pets allowed", slug "pet-friendly"
    "shuttle": (2949,),  # Free airport shuttle
}

# The virtual param the model sees on search_offers. The enum closes the world:
# nothing the model can emit is un-honorable by the table below.
_AMENITIES_PROPERTY: dict[str, Any] = {
    "type": "array",
    "items": {"type": "string", "enum": list(EQUIPMENT_IDS)},
    "description": (
        "Canonical keys of amenities the user explicitly asked the hotel to "
        "HAVE in this request. Include ONLY requested amenities — never the "
        "rest of the list, and never an amenity the user negated or excluded "
        "('sans piscine' / 'no pool' means: do not include pool AND do not "
        "include other keys). Omit entirely when none was requested."
    ),
}

# Same self-configured stdout logger as dayuse_agent_common.metrics — its
# handler is installed on import (agent.py imports those callbacks first).
# GDPR posture: counts only, never the requested keys (an amenity preference is
# user content, same rule as never logging the searched city).
_metrics_logger = logging.getLogger("dayuse.metrics")


def equipment_ids_for(amenities: list[str] | None) -> list[int]:
    """The `hotelEquipmentIds` for canonical amenity keys — ordered, deduped;
    unknown keys are ignored (the enum should prevent them, the table decides)."""
    ids: list[int] = []
    for amenity in amenities or []:
        for equipment_id in EQUIPMENT_IDS.get(amenity, ()):
            if equipment_id not in ids:
                ids.append(equipment_id)
    return ids


def _canonical_keys(values: Any) -> list[str]:
    """Lowered/stripped keys of `values` that exist in the table — anything
    else (hallucinated key, legacy profile junk, non-string) is dropped."""
    keys: list[str] = []
    if not isinstance(values, list):
        return keys
    for value in values:
        if not isinstance(value, str):
            continue
        key = value.strip().lower()
        if key in EQUIPMENT_IDS and key not in keys:
            keys.append(key)
    return keys


def _profile_amenities(tool_context: Any) -> Any:
    """`profile_in.amenities` from the request DataPart riding
    `tool_context.user_content` (the a2a→genai conversion re-wraps the inbound
    DataPart in the same tag envelope `find_datapart` decodes). Missing or
    undecodable → None: the filter simply isn't accumulated, never a crash."""
    content = getattr(tool_context, "user_content", None)
    parts = getattr(content, "parts", None) if content is not None else None
    data = find_datapart(parts)
    if isinstance(data, dict):
        profile = data.get("profile_in")
        if isinstance(profile, dict):
            return profile.get("amenities")
    return None


def inject_amenities_declaration(callback_context: Any, llm_request: Any) -> None:
    """`before_model_callback`: widen the search_offers declaration with the
    virtual `amenities` enum param.

    Runs AFTER ADK's preprocess appended the tool declarations, so the
    declaration is there to widen; declarations are rebuilt on every model
    call, so the per-request assignment is idempotent. `parameters_json_schema`
    REFERENCES the McpTool's cached inputSchema — deepcopy before widening,
    never mutate the pristine schema in place. If a future ADK stops exposing
    the schema as a dict, this no-ops: the model just can't emit the arg and
    the profile-union leg of `enforce_equipment_filters` keeps filtering."""
    config = getattr(llm_request, "config", None)
    for tool_entry in getattr(config, "tools", None) or []:
        for decl in getattr(tool_entry, "function_declarations", None) or []:
            if getattr(decl, "name", None) != "search_offers":
                continue
            schema = getattr(decl, "parameters_json_schema", None)
            if not isinstance(schema, dict):
                return None
            widened = copy.deepcopy(schema)
            widened.setdefault("properties", {})["amenities"] = copy.deepcopy(
                _AMENITIES_PROPERTY
            )
            decl.parameters_json_schema = widened
            return None
    return None


def enforce_equipment_filters(
    tool: Any, args: dict[str, Any], tool_context: Any
) -> dict[str, Any] | None:
    """`before_tool_callback` (wired LAST — must only run when the call will
    actually proceed): the ONLY writer of equipment-ID filters. Always returns
    None so the chain proceeds; mutates `args` in place (ADK passes the same
    dict to the real call)."""
    name = getattr(tool, "name", "") or ""
    if name == "find_hotel_by_name":
        # Cheap insurance: the model was taught a virtual arg this tool's real
        # additionalProperties:false schema forbids — never let it leak.
        args.pop("amenities", None)
        return None
    if name != "search_offers":
        return None

    # The LLM never owns a filter value — this alone kills the hallucinated-ID bug.
    args.pop("hotelEquipmentIds", None)
    args.pop("roomEquipmentIds", None)

    llm_keys = _canonical_keys(args.pop("amenities", None))
    profile_keys = _canonical_keys(_profile_amenities(tool_context))
    requested = profile_keys + [key for key in llm_keys if key not in profile_keys]

    ids = equipment_ids_for(requested)
    if ids:
        args["hotelEquipmentIds"] = ids
        _metrics_logger.info(
            "dayuse_metric=amenity_filter agent=b2c_hotel_search n_keys=%d n_ids=%d",
            len(requested),
            len(ids),
        )
    # Explicitly [] when none — the stamping/delta steps must never see a stale value.
    tool_context.state[STATE_APPLIED_AMENITIES_KEY] = requested
    return None
