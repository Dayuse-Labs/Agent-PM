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

from hotel_search_agent.response_bridge import (
    STATE_APPLIED_AMENITIES_KEY,
    STATE_PREFERRED_AMENITIES_KEY,
    find_datapart,
    record_guards_fired,
)
from hotel_search_agent.standing import STANDING_EVIDENCE_PROPERTY, STANDING_PROPERTY

EQUIPMENT_IDS: dict[str, tuple[int, ...]] = {
    "pool": (33, 34, 2982, 3000, 3001),  # outdoor, indoor, rooftop pool, pool bar, pool
    # 2026-10-27 (prod session 1eb2430a, « piscine intérieure » in November):
    # strict, never the pool group. Alone in the pool OR-group, so only it matches.
    "indoor_pool": (34,),
    "spa": (35,),
    "gym": (38,),  # Fitness room; 37 "Centre de remise en forme" is a legacy duplicate
    "jacuzzi": (41,),  # "Hot tub", slug "jacuzzi"
    "sauna": (2951,),
    "restaurant": (14,),
    "breakfast": (2992,),  # Breakfast Area
    "pet_friendly": (2956,),  # "Pets allowed", slug "pet-friendly"
    "shuttle": (2949,),  # Free airport shuttle
}

# The virtual params the model sees on search_offers. The enum closes the world:
# nothing the model can emit is un-honorable by the table below.
_AMENITIES_PROPERTY: dict[str, Any] = {
    "type": "array",
    "items": {"type": "string", "enum": list(EQUIPMENT_IDS)},
    "description": (
        "Canonical keys of amenities the user explicitly asked the hotel to "
        "HAVE in this request. Include ONLY requested amenities — never the "
        "rest of the list, and never an amenity the user negated or excluded "
        "('sans piscine' / 'no pool' means: do not include pool AND do not "
        "include other keys). A mood, an occasion or a kind of stay "
        "('romantic', 'anniversary', 'to relax', 'for a nap') is not an "
        "amenity request: no key for it. Omit entirely when none was requested."
    ),
}

# UX1: the other direction. Same closed enum — a key that cannot match a
# filter key cannot retract one.
_AMENITIES_REMOVED_PROPERTY: dict[str, Any] = {
    "type": "array",
    "items": {"type": "string", "enum": list(EQUIPMENT_IDS)},
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

# 2026-10-27 (prod session 1eb2430a, « idéalement option de faire un massage »):
# a wish the user marks optional. Searched with first, then the page is
# completed without it (`completion.py`) — never a hard filter.
_AMENITIES_PREFERRED_PROPERTY: dict[str, Any] = {
    "type": "array",
    "items": {"type": "string", "enum": list(EQUIPMENT_IDS)},
    "description": (
        "Canonical keys of amenities the user would LIKE but marks as optional "
        "('idéalement un spa', 'si possible avec piscine', 'ideally a gym', "
        "'a jacuzzi would be a bonus'). NEVER put a key here and in `amenities` "
        "at the same time. Omit entirely when no wish is marked optional."
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


def _profile_amenities(tool_context: Any, key: str = "amenities") -> Any:
    """`profile_in.<key>` (`amenities` or `preferred_amenities`) from the
    request DataPart riding `tool_context.user_content` (the a2a→genai
    conversion re-wraps the inbound DataPart in the same tag envelope
    `find_datapart` decodes). Missing or undecodable → None: the filter simply
    isn't accumulated, never a crash."""
    content = getattr(tool_context, "user_content", None)
    parts = getattr(content, "parts", None) if content is not None else None
    data = find_datapart(parts)
    if isinstance(data, dict):
        profile = data.get("profile_in")
        if isinstance(profile, dict):
            return profile.get(key)
    return None


def inject_amenities_declaration(callback_context: Any, llm_request: Any) -> None:
    """`before_model_callback`: widen the search_offers declaration with the
    virtual `amenities`/`amenities_removed`/`amenities_preferred` enum params,
    and `standing`.

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
            properties["amenities_preferred"] = copy.deepcopy(_AMENITIES_PREFERRED_PROPERTY)
            # Not an amenity, same mechanism: a closed enum the code maps
            # (`standing.enforce_standing`).
            properties["standing"] = copy.deepcopy(STANDING_PROPERTY)
            properties["standing_evidence"] = copy.deepcopy(STANDING_EVIDENCE_PROPERTY)
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
        args.pop("amenities_preferred", None)
        return None
    if name != "search_offers":
        return None

    # The LLM never owns a filter value — this alone kills the hallucinated-ID bug.
    args.pop("hotelEquipmentIds", None)
    args.pop("roomEquipmentIds", None)

    llm_keys = _canonical_keys(args.pop("amenities", None))
    removed_keys = _canonical_keys(args.pop("amenities_removed", None))
    llm_preferred = [key for key in _canonical_keys(args.pop("amenities_preferred", None)) if key not in llm_keys]
    # A wish now marked optional stops being required.
    profile_keys = [
        key for key in _canonical_keys(_profile_amenities(tool_context)) if key not in llm_preferred
    ]

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
    requested = _strictest_pool([key for key in accumulated if key not in removed])
    preferred = [
        key
        for key in _canonical_keys(_profile_amenities(tool_context, "preferred_amenities")) + llm_preferred
        if key not in requested and key not in removed
    ]
    preferred = list(dict.fromkeys(preferred))
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

    # The first search is filtered on the wishes too; `completion.py` completes
    # a thin page without them. Kept apart in state: only `requested` is ever
    # a hard filter of a later search.
    ids = equipment_ids_for(_strictest_pool(requested + preferred))
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
    tool_context.state[STATE_PREFERRED_AMENITIES_KEY] = preferred
    return None


def _strictest_pool(keys: list[str]) -> list[str]:
    """`indoor_pool` and `pool` together mean the indoor one: the pool ids are
    OR-grouped server-side, so sending both would match any pool."""
    return [key for key in keys if key != "pool"] if "indoor_pool" in keys else keys
