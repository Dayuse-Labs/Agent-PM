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
  closed to `AMENITY_KEYS` — the model only ever extracts INTENT.
- `enforce_equipment_filters` (before_tool) pops that virtual param before the
  MCP server (whose real schema forbids it) can see it, validates every key
  against the table, unions with the accumulated `profile_in.amenities` from
  the request DataPart, and re-writes the hotel/room equipment IDs deterministically —
  after unconditionally dropping whatever the model put there.

UX1 (2026-08-27) — the retraction channel. The union above is deliberate
(`occupancy.py`'s doctrine: filters accumulate, the user must not restate
"avec piscine" every turn), but until now it was the ONLY direction: the
profile could grow and never shrink, so "enleve le spa" replayed the exact
same search. A SECOND virtual param, `amenities_removed`, carries the other
direction — with the same closed enum, because a removal key that cannot match
a filter key removes nothing. It covers both formulations, which are one and
the same business effect (MCP has no negative filter, so "I do not want X" IS
"X is not in the filter"): the retraction of an earlier constraint ("enleve le
spa") and a negation in a fresh request ("un hotel sans piscine"). Precedence
when a key arrives in BOTH fields: the request wins — see
`enforce_equipment_filters`.

ID provenance: original hotel IDs from the MCP referential (2026-07-20),
room IDs and added hotel facilities from live list_amenities scoped calls
(2026-10-09), frozen in contracts/mcp_equipment_scopes.json. Room requirements
are written only to roomEquipmentIds. A bathtub is not the hotel's hot tub;
a facility alone proves neither inclusion in the price nor opening hours.
Generic parking/rooftop remain unmapped; rooftop_bar has its own exact ID.

"""
from __future__ import annotations

import copy
import logging
from typing import Any

from b2c_common.amenities import AMENITY_KEYS

from hotel_search_agent.response_bridge import (
    STATE_APPLIED_AMENITIES_KEY,
    find_datapart,
    record_guards_fired,
)

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
    "elevator": (20,),
    "rooftop_bar": (2981,),
}

# Live list_amenities(scope="room"), 2026-10-09. These IDs constrain the
# offered room/rate plan, not merely an amenity somewhere in the hotel.
ROOM_EQUIPMENT_IDS: dict[str, tuple[int, ...]] = {
    "bathtub": (11,),
    "shower": (12,),
    "air_conditioning": (3,),
    "room_service": (4,),
}

# The virtual params the model sees on search_offers. The enum closes the world:
# nothing the model can emit is un-honorable by the table below.
_AMENITIES_PROPERTY: dict[str, Any] = {
    "type": "array",
    "items": {"type": "string", "enum": list(AMENITY_KEYS)},
    "description": (
        "Canonical keys of amenities the user explicitly asked the hotel to "
        "HAVE in this request. Include ONLY requested amenities — never the "
        "rest of the list, and never an amenity the user negated or excluded "
        "('sans piscine' / 'no pool' means: do not include pool AND do not "
        "include other keys). Omit entirely when none was requested."
    ),
}

# UX1: the other direction. Same closed enum — a key that cannot match a
# filter key cannot retract one.
_AMENITIES_REMOVED_PROPERTY: dict[str, Any] = {
    "type": "array",
    "items": {"type": "string", "enum": list(AMENITY_KEYS)},
    "description": (
        "Canonical keys of amenities the user does NOT want filtered on in "
        "this request — either because they are dropping a constraint they "
        "stated earlier ('enleve le spa', 'finalement sans le spa', 'drop the "
        "pool filter') or because they negated it now ('un hotel sans "
        "piscine', 'no pool'). Include ONLY the keys they dropped or negated. "
        "NEVER put a key here and in `amenities` at the same time, and never "
        "put here an amenity they are asking FOR. Omit entirely when nothing "
        "was dropped or negated."
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
        if key in AMENITY_KEYS and key not in keys:
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
    virtual `amenities`/`amenities_removed` enum params.

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
            properties = widened.setdefault("properties", {})
            properties["amenities"] = copy.deepcopy(_AMENITIES_PROPERTY)
            properties["amenities_removed"] = copy.deepcopy(_AMENITIES_REMOVED_PROPERTY)
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
        # Cheap insurance: the model was taught virtual args this tool's real
        # additionalProperties:false schema forbids — never let them leak.
        args.pop("amenities", None)
        args.pop("amenities_removed", None)
        return None
    if name != "search_offers":
        return None

    # The LLM never owns a filter value — this alone kills the hallucinated-ID bug.
    args.pop("hotelEquipmentIds", None)
    args.pop("roomEquipmentIds", None)

    llm_keys = _canonical_keys(args.pop("amenities", None))
    removed_keys = _canonical_keys(args.pop("amenities_removed", None))
    profile_keys = _canonical_keys(_profile_amenities(tool_context))
    content = getattr(tool_context, "user_content", None)
    data = find_datapart(getattr(content, "parts", None))
    params = data.get("query_params") if isinstance(data, dict) else None
    if isinstance(params, dict) and params.get("amenities_authoritative") is True:
        # Concierge applied the current, quoted intent before the A2A call.
        # Preserve that snapshot even if this model repeats an old filter.
        llm_keys, removed_keys = [], []

    # UX1 precedence — a key in BOTH fields is APPLIED, never removed. This is
    # not a preference, it is the fail-safe direction against gpt-4o-mini's
    # negation-inversion trap (lesson S10, which `_AMENITIES_PROPERTY` above is
    # already written for): on "je veux une piscine" the model can copy the key
    # into both fields, and an explicit request made THIS turn must never be
    # cancelled by a removal signal. The user can always retract next turn; a
    # silently ignored request has no such recourse.
    conflicts = [key for key in removed_keys if key in llm_keys]
    removed = [key for key in removed_keys if key not in llm_keys]

    accumulated = profile_keys + [key for key in llm_keys if key not in profile_keys]
    requested = [key for key in accumulated if key not in removed]
    if len(requested) < len(accumulated):
        # OBS3 guard #15: the retraction actually took a key out of the filter
        # that would otherwise have been applied. `record_guards_fired` is the
        # single writer of the leaf's guard state (PR #95) — never a 2nd path.
        record_guards_fired(tool_context, ["filter_relaxation_honored"])
    if conflicts:
        # RGPD: counts only, never the keys — same discipline as amenity_filter.
        _metrics_logger.info(
            "dayuse_metric=amenity_filter_conflict agent=b2c_hotel_search n_conflicts=%d",
            len(conflicts),
        )

    ids = equipment_ids_for(requested)
    room_ids = list(dict.fromkeys(
        equipment_id for key in requested for equipment_id in ROOM_EQUIPMENT_IDS.get(key, ())
    ))
    if room_ids:
        args["roomEquipmentIds"] = room_ids
    if ids:
        args["hotelEquipmentIds"] = ids
        _metrics_logger.info(
            "dayuse_metric=amenity_filter agent=b2c_hotel_search n_keys=%d n_ids=%d",
            len(requested),
            len(ids),
        )
    # Explicitly [] when none — the stamping/delta steps must never see a stale
    # value, AND this is the sentinel `emit_search_datapart` uses to tell "the
    # search ran with no filter" (→ an explicit empty set) apart from "no search
    # ran this turn" (→ key absent → carryover). Never write it anywhere else.
    tool_context.state[STATE_APPLIED_AMENITIES_KEY] = requested
    return None
