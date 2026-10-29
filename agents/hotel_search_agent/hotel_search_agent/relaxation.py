"""« Aucune offre » : the bounded rescue of an empty search, and the user's own
request to loosen it (point 3, prod 2026-10-27/28).

36 empty searches after #160, read from their real `search_offers` arguments
(Langfuse): 17 carried a hard amenity filter (jacuzzi 41, spa 35, sauna 2951…),
16 a strict time slot, 13 ran the same day in the evening, 4 a party size; a
2 km ring around « la métropole lilloise » and « wan chai side ». And the user's
« gebied vergroten », « quitar un filtro », « aumentar el presupuesto » re-ran
the very same search. agent-usa relaxed an empty search (amenities that were not
a must-have, zone, budget) and said what it relaxed; this module does the same
from facts only — the arguments actually sent, MCP's own counts, the GeoIntent
`kind` the model wrote and the place type Mapbox returned. Nothing here reads
the user's words.

1. The rescue (`rescue_empty_search_after_tool`, after-tool). When the first
   page comes back EMPTY from MCP, ONE rescue per turn, at most
   `MAX_RESCUE_CALLS` MCP calls (one less when the next-day probe already spent
   one), in the order of what each step SAVES (Fabien's replay on MCP prod,
   2026-10-28, 27 groups of empty searches, one criterion removed at a time:
   amenity 14/16, radius ×2 11/26, time slot 1/10 — validated by Victor):
     amenities — the amenity filter is dropped, unless the model marked it
                 `amenities_must_have` (then only the optional wishes go);
     radius    — the next ring (50 km, then 100 km), nearest first;
     timeslot  — the slot is dropped: the cards are the closest to it, and say so
                 (the concierge's `window_fallback`).
   The first call relaxes the first applicable step; the second adds the next
   one. When the search ran on TODAY and today's window is closing (MCP
   counts offers past their cutoff: `totalBeforeCutoff` > `total`), every
   relaxed call is aimed at the DAY AFTER: the next-day probe already tried it
   strict, so the rescue is « the day after, minus the next step » — never a
   relaxed call on a day whose bookings are closed (R1, review of #173).
   What was relaxed rides the DataPart (`relaxation`) and the concierge writes
   it in code, before the synthesis.

2. The request (`read_relax_request` / `apply_relax_request`, before-tool). The
   model labels a request to loosen the CURRENT search with no new value
   (`relax`: area, filters, time, budget — a typed enum in the widened
   declaration); a recovery chip clicked in the concierge arrives as
   `query_params.relax`. Code applies it to the arguments: a nearby ring, the
   amenity filters removed (else the slot, else the standing), the slot
   removed, the cap raised by `BUDGET_RAISE_FACTOR` for this search. When there
   was nothing to loosen, the DataPart says so — no more « I can't widen ».

3. The ring floor (`response_bridge.radius_floor_km`). An area the model labelled `region` /
   `admin_district`, or a place Mapbox typed as a region or district, is
   searched on a city ring at least; a `neighborhood` (or a Mapbox
   neighbourhood / locality / place) on 5 km at least: never the 2 km ring of a
   building that happens to carry the area's name.
"""
from __future__ import annotations

import copy
import logging
import time
from datetime import date, timedelta
from typing import Any

from hotel_search_agent.equipment_ids import equipment_ids_for
from hotel_search_agent.extra_calls import extra_call
from hotel_search_agent.response_bridge import (
    BUDGET_RAISE_FACTOR,
    NEARBY_RADIUS_KM,
    SITE_RADII_KM,
    STATE_AMENITIES_MUST_HAVE_KEY,
    STATE_APPLIED_AMENITIES_KEY,
    STATE_DATE_FALLBACK_KEY,
    STATE_DAYPART_KEY,
    STATE_EXACT_WINDOW_KEY,
    STATE_NEARBY_KEY,
    STATE_NEXT_DAY_PROBED_KEY,
    STATE_PREFERRED_AMENITIES_KEY,
    STATE_RELAX_APPLIED_KEY,
    STATE_RELAX_REQUEST_KEY,
    STATE_RESCUE_KEY,
    STATE_RESCUE_RAN_KEY,
    STATE_SEARCH_DATE_KEY,
    STATE_STANDING_KEY,
    pool_before_cutoff,
    read_query_params,
    read_structured_payload,
)
from hotel_search_agent.schema_guard import drop_args_outside_schema

_metrics_logger = logging.getLogger("dayuse.metrics")

#: The rescue's MCP calls per turn, the next-day probe's included (it shares
#: the dead end): the turn already spends a geocode, two model calls and a
#: search, and one leaf turn went past the concierge's 30 s once.
MAX_RESCUE_CALLS = 2
#: MCP's radius when `radiusKm` is absent (a city search).
MCP_DEFAULT_RADIUS_KM = 20.0

RELAX_ACTIONS = ("area", "filters", "time", "budget")

#: The concierge's recovery chip of this call (`query_params.relax`), apart
#: from the model's own reading: only a chip the user clicked is answered
#: « nothing to remove » (`relaxation_notice`, 2026-10-29).
STATE_RELAX_CHIP_KEY = "temp:hotel_search_relax_chip"

_RELAX_PROPERTY: dict[str, Any] = {
    "type": "string",
    "enum": list(RELAX_ACTIONS),
    "description": (
        "ONLY when THIS message asks to LOOSEN the current search without giving a new "
        "value: 'area' = widen the area / try nearby areas; 'filters' = remove a filter / "
        "fewer criteria, without naming which; 'time' = another or any time of day, no "
        "hour given; 'budget' = raise the budget, no amount given. Omit it otherwise "
        "(a new place, date, hour, amount or a named amenity goes in its own argument)."
    ),
}
_MUST_HAVE_PROPERTY: dict[str, Any] = {
    "type": "boolean",
    "description": (
        "true when the requested amenity IS what the user is looking for: the request "
        "is about it ('a spa afternoon', 'find a room with a jacuzzi', 'a pool day', "
        "'only with', 'must have', or insisting after being told none had it). false when "
        "it comes on top of another purpose, as a plus ('near the airport, ideally with a "
        "pool'). false: when no hotel has it, the system shows the closest hotels without "
        "it and says so; true: it widens the area instead."
    ),
}


def inject_relaxation_declaration(callback_context: Any, llm_request: Any) -> None:
    """`before_model_callback`, after `inject_amenities_declaration`: adds the
    virtual `relax` and `amenities_must_have` params to search_offers. Same
    deepcopy discipline: the McpTool's cached schema is never mutated."""
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
            properties["relax"] = copy.deepcopy(_RELAX_PROPERTY)
            properties["amenities_must_have"] = copy.deepcopy(_MUST_HAVE_PROPERTY)
            decl.parameters_json_schema = widened
            return None
    return None


# --- the user's request -------------------------------------------------------------------------


def read_relax_request(tool: Any, args: dict[str, Any], tool_context: Any) -> None:
    """`before_tool_callback`, before `inject_landmark_radius`: pops the two
    virtual params (any tool — `find_hotel_by_name` must never send them),
    merges the concierge's chip (`query_params.relax`), and turns « area » into
    the nearby flag the ring reads."""
    relax = args.pop("relax", None)
    must_have = args.pop("amenities_must_have", None)
    if getattr(tool, "name", "") != "search_offers":
        return None
    actions = [relax] if relax in RELAX_ACTIONS else []
    chip = read_query_params(tool_context).get("relax")
    if chip in RELAX_ACTIONS and chip not in actions:
        actions.append(chip)
    state = tool_context.state
    state[STATE_RELAX_REQUEST_KEY] = actions
    state[STATE_RELAX_CHIP_KEY] = chip if chip in RELAX_ACTIONS else None
    state[STATE_AMENITIES_MUST_HAVE_KEY] = must_have is True
    if "area" in actions:
        state[STATE_NEARBY_KEY] = True
    return None


def _drop_time(args: dict[str, Any], state: Any) -> bool:
    had = "timeSlot" in args or state.get(STATE_DAYPART_KEY) or state.get(STATE_EXACT_WINDOW_KEY)
    args.pop("timeSlot", None)
    args.pop("timeSlotMode", None)
    state[STATE_DAYPART_KEY] = None
    state[STATE_EXACT_WINDOW_KEY] = None
    return bool(had)


def apply_relax_request(tool: Any, args: dict[str, Any], tool_context: Any) -> None:
    """`before_tool_callback`, after every writer of the arguments and before
    `drop_args_outside_schema`: applies « filters », « time » and « budget »
    (« area » was applied by the ring) and records what changed, or that there
    was nothing to change."""
    if getattr(tool, "name", "") != "search_offers":
        return None
    state = tool_context.state
    actions = state.get(STATE_RELAX_REQUEST_KEY) or []
    if not actions:
        return None
    applied: dict[str, Any] = {"requested": list(actions)}
    chip = state.get(STATE_RELAX_CHIP_KEY)
    if chip in actions:
        applied["chip"] = chip
    removed: list[str] = []
    if "filters" in actions:
        amenities = list(state.get(STATE_APPLIED_AMENITIES_KEY) or []) + [
            key for key in state.get(STATE_PREFERRED_AMENITIES_KEY) or []
            if key not in (state.get(STATE_APPLIED_AMENITIES_KEY) or [])
        ]
        if amenities or args.get("hotelEquipmentIds"):
            args.pop("hotelEquipmentIds", None)
            args.pop("roomEquipmentIds", None)
            # Written back empty: the profile drops the filters (same op as
            # « enlève le spa »), they do not come back on the next turn.
            state[STATE_APPLIED_AMENITIES_KEY] = []
            state[STATE_PREFERRED_AMENITIES_KEY] = []
            removed.append("amenities")
            applied["amenities"] = amenities
        elif _drop_time(args, state):
            removed.append("timeslot")
        elif args.get("starRatings"):
            args.pop("starRatings", None)
            state[STATE_STANDING_KEY] = ""
            removed.append("standing")
    if "time" in actions and "timeslot" not in removed and _drop_time(args, state):
        removed.append("timeslot")
    if removed:
        applied["removed"] = removed
    elif "filters" in actions or "time" in actions:
        applied["nothing_to_remove"] = True
    if "budget" in actions:
        cap = args.get("priceRangeMax")
        if isinstance(cap, (int, float)) and not isinstance(cap, bool) and cap > 0:
            raised = round(float(cap) * BUDGET_RAISE_FACTOR, 2)
            args["priceRangeMax"] = raised
            applied["budget"] = {"from": float(cap), "to": raised}
        else:
            applied["budget_factor"] = BUDGET_RAISE_FACTOR
    state[STATE_RELAX_APPLIED_KEY] = applied
    return None


# --- the rescue ---------------------------------------------------------------------------------


def closing_today(structured: Any) -> bool:
    """Offers matched today and none is bookable any more: today's window is
    closing — the next day is the cure, not a wider net."""
    if not isinstance(structured, dict) or structured.get("results"):
        return False
    try:
        after = int(structured.get("total") or 0)
    except (TypeError, ValueError):
        after = 0
    return pool_before_cutoff(structured) > after


def next_radius_km(args: dict[str, Any]) -> float | None:
    sent = args.get("radiusKm")
    radius = float(sent) if isinstance(sent, (int, float)) and not isinstance(sent, bool) else MCP_DEFAULT_RADIUS_KM
    if radius < SITE_RADII_KM[-1]:
        return SITE_RADII_KM[-1]
    if radius < NEARBY_RADIUS_KM:
        return NEARBY_RADIUS_KM
    return None


def _relaxed_amenities(state: Any) -> tuple[list[str], list[str]]:
    """(keys relaxed, keys still required) for the amenities step."""
    required = list(state.get(STATE_APPLIED_AMENITIES_KEY) or [])
    preferred = [k for k in state.get(STATE_PREFERRED_AMENITIES_KEY) or [] if k not in required]
    if state.get(STATE_AMENITIES_MUST_HAVE_KEY):
        return preferred, required
    return required + preferred, []


def plan_steps(args: dict[str, Any], state: Any) -> list[str]:
    """The applicable steps, in order (most saving first), from the arguments
    actually sent."""
    steps: list[str] = []
    if args.get("hotelEquipmentIds") and _relaxed_amenities(state)[0]:
        steps.append("amenities")
    if next_radius_km(args) is not None:
        steps.append("radius")
    if args.get("timeSlot"):
        steps.append("timeslot")
    return steps


def relaxed_args(args: dict[str, Any], steps: list[str], state: Any) -> dict[str, Any]:
    relaxed = {key: value for key, value in args.items() if key != "from"}
    if "timeslot" in steps:
        relaxed.pop("timeSlot", None)
        relaxed.pop("timeSlotMode", None)
    if "amenities" in steps:
        ids = equipment_ids_for(_relaxed_amenities(state)[1])
        if ids:
            relaxed["hotelEquipmentIds"] = ids
        else:
            relaxed.pop("hotelEquipmentIds", None)
        relaxed.pop("roomEquipmentIds", None)
    if "radius" in steps:
        relaxed["radiusKm"] = next_radius_km(args)
        relaxed["sortBy"] = "distance"
    return relaxed


def _next_day(iso: Any) -> str | None:
    try:
        return (date.fromisoformat(str(iso)) + timedelta(days=1)).isoformat()
    except ValueError:
        return None


async def rescue_empty_search_after_tool(
    tool: Any, args: dict[str, Any], tool_context: Any, tool_response: Any
) -> None:
    """`after_tool_callback`, after the next-day probe and before
    `complete_thin_search_after_tool` (which stands down once this ran) and
    `capture_after_tool` (which consumes `STATE_RESCUE_KEY`). Always None."""
    if getattr(tool, "name", "") != "search_offers":
        return None
    if not isinstance(tool_response, dict) or tool_response.get("isError"):
        return None
    if tool_response.get("ok") is False or tool_response.get("error"):
        return None
    state = tool_context.state
    if state.get(STATE_RESCUE_RAN_KEY) or args.get("from"):
        return None
    structured = read_structured_payload(tool_response)
    if not isinstance(structured, dict) or structured.get("results"):
        return None
    if isinstance(state.get(STATE_DATE_FALLBACK_KEY), dict):
        return None  # the next-day probe already found the day after
    state[STATE_RESCUE_RAN_KEY] = True
    probed = bool(state.get(STATE_NEXT_DAY_PROBED_KEY))
    calls_left = MAX_RESCUE_CALLS - int(probed)
    search_date = state.get(STATE_SEARCH_DATE_KEY) if isinstance(state.get(STATE_SEARCH_DATE_KEY), dict) else {}
    searched = search_date.get("date") or args.get("date")
    # Today, and today's window closing: every relaxed call is for the day
    # after (the probe tried it strict). Else the day searched.
    same_day = bool(search_date.get("same_day"))
    closing = same_day and closing_today(structured)
    day = _next_day(searched) if closing else searched
    steps = plan_steps(args, state)
    if not steps or not day:
        return None
    started = time.monotonic()
    calls = 0
    used: list[str] = []
    upcoming = steps[:1]
    sent: dict[str, Any] = {}
    found: dict[str, Any] | None = None
    while calls < calls_left and upcoming:
        used = upcoming
        sent = {**relaxed_args(args, used, state), "date": day}
        drop_args_outside_schema(tool, sent, tool_context)
        status, payload = await extra_call(tool, sent, tool_context, kind="rescue")
        if status != "ok":
            # R2 (review of #173): an error (a 429 included) is not « empty »:
            # the ladder stops, and so does the completion (`extra_calls`).
            _log("error" if status == "error" else "skipped", started, calls, 0)
            return None
        calls += 1
        if payload is not None and payload.get("results"):
            found = payload
            break
        if not closing and same_day and closing_today(payload):
            # The relaxed search matched hotels today, all past their cutoff
            # (Wan Chai at 21h once the slot went): the same relaxation, the
            # day after — never another relaxation on a closed day.
            closing, day, upcoming = True, _next_day(searched), used
        else:
            upcoming = steps[: len(used) + 1] if len(used) < len(steps) else []
    _log("ok" if found else "empty", started, calls, len(used) if found else 0)
    if found is None:
        return None
    if closing:
        used = [*used, "next_day"]
    rescue: dict[str, Any] = {"payload": found, "steps": used, "searched_date": searched}
    if "radius" in used:
        rescue["radius_km"] = sent.get("radiusKm")
    if "amenities" in used:
        rescue["amenities"] = _relaxed_amenities(state)[0]
    if "next_day" in used:
        rescue["offered_date"] = sent.get("date")
    state[STATE_RESCUE_KEY] = rescue
    return None


def _log(status: str, started: float, calls: int, steps: int) -> None:
    # Counts only — never a place, an amenity or a date (GDPR, like the D+1 probe).
    _metrics_logger.info(
        "dayuse_metric=search_rescue agent=b2c_hotel_search status=%s calls=%d steps=%d ms=%d",
        status, calls, steps, int((time.monotonic() - started) * 1000),
    )
