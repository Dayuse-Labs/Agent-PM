"""response_bridge.py — the leaf's structured A2A DataPart out + tool-payload truncation.

Two long-deferred gaps (S4/S5/S6 "Reste") that together caused the orchestrator
to see "aucun résultat de recherche":

1. **No structured results.** This leaf is an `LlmAgent`: without this bridge it
   answers in PROSE only, so the orchestrator's `_run_leaf` (which looks for an
   A2A DataPart via `find_datapart`) got nothing → `hotels` empty → the façade
   showed no cards even on a successful search. `emit_search_datapart` (an
   `after_agent_callback`) now emits `{results, profile_delta}` as a real
   DataPart the orchestrator already knows how to decode — byte-compatible with
   `b2c_concierge.a2a_datapart.encode_datapart` (same ADK tag/mime envelope), so
   no dependency on the orchestrator package (leaves stay independent, B3).

2. **24k-token tool payload → 10 s budget blown.** `search_offers` returns a
   large result (structured content + a duplicated text mirror). Fed straight
   into the model it made the final LLM pass ~11 s, over the orchestrator's 10 s
   leaf budget → intermittent TimeoutError → honest degradation. `capture_after_tool`
   (an `after_tool_callback`) replaces that payload with the compact top-5 the
   model needs to write its prose — the orchestrator gets the FULL structured
   results from the DataPart, not from the model's text.

State hand-off: `capture_after_tool` stashes the normalized results (and the
geocode `profile_delta` + resolved ISO `country_code`) in `tool_context.state`
under `temp:` keys (invocation-scoped, never persisted — the leaf is stateless);
`emit_search_datapart` reads them back at the end of the turn.

`profile_delta` key mapping: geocode returns `last_city`/`last_state_context`,
but the orchestrator's `apply_profile_delta` reads `city`/`state_anchor` (the S5
naming gap). The mapping happens HERE, when emitting — the orchestrator owns the
profile schema, so the leaf emits in that schema. The turn's budget/time-slot
(`budget_max` + `timeslot_start`/`timeslot_end`, each with a `*_request_source`)
are captured from the real `search_offers` args and mapped the same way (S14 —
closing the S9/S12 gap that left the concierge's budget/timeslot guards dormant).
"""
from __future__ import annotations

import json
import logging
import math
import time
from typing import Any, Iterable

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import (
    A2A_DATA_PART_END_TAG,
    A2A_DATA_PART_START_TAG,
    A2A_DATA_PART_TEXT_MIME_TYPE,
)
from google.adk.models.llm_response import LlmResponse
from google.genai import types as genai_types

from b2c_common import build_hotel_page_url, display_price_euro, hotel_currency_price, with_checkin_date
from b2c_common.search_page import build_search_page_url, search_page_from
from b2c_common.timeslot import (
    DAYPART_HOURS,
    requested_hours,
    slot_covers_window,
    slot_overlaps_daypart,
    window_fallback_line,
)
from hotel_search_agent.inventory import haversine_km
from hotel_search_agent.mcp_guard import classify_mcp_error

# The concierge reports AT MOST 5 (ground-truth cap) — match it so the model
# never ingests more than the caller can use. Public (S-G5): also the page
# size the pagination bridge uses to turn profile_in.search_cursor into the
# search_offers `from` offset (one page == one shown shortlist).
MAX_RESULTS = 5

# Tools whose result is a hotel list/identity worth surfacing as `results`.
_TARGET_TOOLS = {"search_offers", "find_hotel_by_name"}

# temp: → invocation-scoped, discarded after the turn (leaf stays stateless).
_STATE_RESULTS_KEY = "temp:hotel_search_results"
_STATE_DELTA_KEY = "temp:hotel_search_profile_delta"
_STATE_COUNTRY_KEY = "temp:hotel_search_country_code"
# The resolved geocode anchor (lat/lon/label/type) stashed by the geocode branch,
# and the per-search distance origin derived from it (A8-a: verifiable ranking —
# cards carry coords + distance from the anchor, so shortlist relevance stops
# being unmeasurable). Additive to the DataPart; the concierge ignores unknown keys.
_STATE_ANCHOR_KEY = "temp:hotel_search_anchor"
_STATE_DISTANCE_ORIGIN_KEY = "temp:hotel_search_distance_origin"
# OBS3 (2026-08-26): the names of the deterministic guards that fired in THIS
# leaf this turn, on their way to the concierge's `score_guards`.
#
# Why it did not exist before: 5 of the 13 `GUARD_SCORE_NAMES` fire here, not in
# the concierge — and nothing ever carried them across A2A, so `score_guards`
# emitted them as 0.0 on every single turn, forever. `scores.py` says as much
# ("a later session wires their call sites"). The visible consequence: the
# Toulon trace showed `guard_geocode_echo_back = false`, which read as a
# structural false negative of the guard when it was really an unwired score.
_STATE_GUARDS_KEY = "temp:hotel_search_guards_fired"
# mcp-dayuse#8: the degraded paths this turn still answered on
# (`FALLBACK_SCORE_NAMES`), on their way to the concierge's `score_fallbacks`.
_STATE_FALLBACKS_KEY = "temp:hotel_search_fallbacks"
# "rejected" or "failed" (`mcp_guard.classify_mcp_error`): a rejected request
# must not be answered with "retry in a moment".
_STATE_MCP_ERROR_KEY = "temp:hotel_search_mcp_error"
# The name `find_hotel_by_name` could not find, so the concierge can say so
# when the turn answers with other hotels (QA trace 6ef04c80).
_STATE_NAMED_NOT_FOUND_KEY = "temp:hotel_search_named_not_found"
# The budget / time-slot the model actually sent search_offers, captured from
# the tool args (search_offers has NATIVE priceRangeMax/timeSlot params — no
# virtual param needed, unlike amenities in S10) and mapped to the profile in
# emit. This is what lets the concierge's S12 guards (budget-vs-duration,
# auto-widen/exhaustion, provenance) finally run on real traffic (S9/S12 gap).
_STATE_BUDGET_TIMESLOT_KEY = "temp:hotel_search_budget_timeslot"
_STATE_RADIUS_KEY = "temp:hotel_search_radius_km"
_STATE_SEARCH_PAGE_KEY = "temp:hotel_search_search_page"
# Public (unlike the keys above): written by equipment_ids.enforce_equipment_filters,
# read back here for card stamping + the profile_delta — same cross-callback
# `temp:` hand-off as _STATE_COUNTRY_KEY.
STATE_APPLIED_AMENITIES_KEY = "temp:hotel_search_applied_amenities"
# S-G6: written by datetime_resolver.resolve_search_date (public, same cross-
# callback pattern as STATE_APPLIED_AMENITIES_KEY) — the resolved ISO date +
# its provenance, mapped into profile_delta by emit_search_datapart. Absent
# when the turn carried over a prior date with no fresh label (nothing new to
# persist — carryover already holds via the profile's own `date` field).
STATE_RESOLVED_DATE_KEY = "temp:hotel_search_resolved_date"
# S-G6: written by datetime_resolver.resolve_search_timeslot — the EXACT
# requested window in minutes-of-day ({"start_total": int|None, "end_total":
# int|None}), preserved here because the real search_offers call only accepts
# integer startHour/endHour (probed live 2026-07-23: no minute fields exist
# server-side) — this is what lets capture_after_tool recover the true
# requested minutes for profile.timeslot_start/end and apply the exact-window
# post-filter, after the before_tool_callback has already floored/ceiled the
# args sent to MCP.
STATE_EXACT_WINDOW_KEY = "temp:hotel_search_exact_window"
# mcp-dayuse#8, option B: the daypart ("afternoon"...) this search filtered on,
# written by datetime_resolver.resolve_search_timeslot.
STATE_DAYPART_KEY = "temp:hotel_search_daypart"
# S-G6: set when the exact-window post-filter would have emptied the result
# set entirely — the leaf then falls back to the coarser (hour-rounded)
# results instead of a silent 0, and the outcome text discloses the fallback.
_STATE_TIMESLOT_FALLBACK_KEY = "temp:hotel_search_timeslot_fallback"
# S-CX6: the date this turn's search actually ran on + whether that date is the
# session's own "today" — written by datetime_resolver.resolve_search_date on
# EVERY search (unlike STATE_RESOLVED_DATE_KEY, which only persists a fresh
# label). Public, same cross-callback `temp:` hand-off. Three consumers: the
# next-day probe's firing condition, the outcome text (a dead-end that never
# names the date it searched is what made "no results" look like a display bug,
# Fabien's session 2026-07-27), and the DataPart the concierge reads.
STATE_SEARCH_DATE_KEY = "temp:hotel_search_search_date"
# S-CX6: the D+1 payload stashed by datetime_resolver.probe_next_day_after_tool
# when a SAME-DAY search came back empty over a non-empty pool (`total` > 0 with
# `results` == [] — every day-use offer's `cutoffDeadlineUtc` falls on the stay
# date itself, latest 16h Paris measured over 63 offers, so after that hour
# "today" is dead pool-wide). capture_after_tool consumes it below.
STATE_DATE_FALLBACK_KEY = "temp:hotel_search_date_fallback"
# S-G4 per-phase instrumentation: dayuse_agent_common's tool_timing_before/after
# already emit a `dayuse_metric=tool_call tool=geocode_location` / `tool=search_offers`
# row (geocode ms / MCP ms) and llm_timing_before/after a `dayuse_metric=llm_call`
# row (the leaf's own reasoning-pass ms) — this key adds the missing 4th number
# (total turn ms) so a live probe can diff total against the sum of the other
# 3 and see how much is unaccounted for (A2A/ADK overhead, MCP session setup)
# instead of just the phases that happen to call a tool or the model.
_STATE_TURN_T0_KEY = "temp:hotel_search_turn_t0"
# S-G10 (D3): the geocode clarify question of THIS turn — emitted as a
# deterministic `requires_clarification` DataPart flag so the orchestrator's
# facade can report the clarification honestly (it used to be hardcoded False).
_STATE_CLARIFY_QUESTION_KEY = "temp:hotel_search_clarify_question"
# S-CX2 (audit CX 2026-07-24, F2): the MCP search tools were unavailable THIS
# turn (circuit open observed on a call). Together with the anchor-without-
# results signal in emit_search_datapart, this drives the deterministic
# `status=search_unavailable` DataPart — the orchestrator then answers with
# its honest degraded template instead of synthesizing a FALSE "no offers in
# <city>" from a turn where the search never actually ran.
_STATE_SEARCH_UNAVAILABLE_KEY = "temp:hotel_search_search_unavailable"

# The leaf ALWAYS reports a non-explicit provenance for a captured budget/
# time-slot: the concierge's budget-integrity guard (P1) owns the upgrade to
# "explicit" when the user's message was a bare number/time. Mirrors
# b2c_concierge.profile.BUDGET_SOURCE_FLEXIBLE_DEFAULT — kept as a local literal,
# never imported (the leaf must not depend on the orchestrator package, B3).
_REQUEST_SOURCE_FLEXIBLE = "flexible_default"

# Same stdout metrics logger as equipment_ids.py / dayuse_agent_common.metrics.
# GDPR posture: presence FLAGS only (0/1), never the budget amount or the hours —
# a budget/time preference is user content, same rule as never logging the city.
_metrics_logger = logging.getLogger("dayuse.metrics")


def _coord(value: Any) -> float | None:
    """A finite lat/lon float, else None — never lets a string/garbage coordinate
    reach a distance computation or a card."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if -180.0 <= f <= 180.0 else None


def _finite_float(value: Any) -> float | None:
    """A finite float, else None — deliberately NOT `_coord` (whose ±180 clamp
    is a coordinate invariant, and would silently swallow a legitimate score)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _iso_alpha2(value: Any) -> str | None:
    """ISO alpha-2 country code or None — never lets a full country name
    ("France") masquerade as a code (the widget's market table is ISO-keyed)."""
    if isinstance(value, str):
        candidate = value.strip()
        if len(candidate) == 2 and candidate.isalpha():
            return candidate.upper()
    return None


def _iso_currency(value: Any) -> str | None:
    """ISO 4217 alpha-3 currency code or None. S-G7: live-probed 2026-07-23,
    `search_offers`/`get_hotel_details` return a per-hotel `currencyCode`
    (e.g. "USD" for Miami, "GBP" for London) — the hotel's OWN local
    currency. It is purely informational: the only numeric price fields
    (`priceEuro`/`priceEuroWithBookingFees`) stay EUR cents regardless of
    this code (verified live: a Miami hotel's `priceEuro` matches its
    already-known EUR quote even though its `currencyCode` is "USD") — no
    conversion exists server-side. Stamping it on the card is what lets the
    concierge's synthesis disclose honestly when the displayed EUR price
    isn't the hotel's own currency, instead of implying it is."""
    if isinstance(value, str):
        candidate = value.strip()
        if len(candidate) == 3 and candidate.isalpha():
            return candidate.upper()
    return None


# --- DataPart encoding (byte-identical to b2c_concierge.a2a_datapart.encode_datapart) --------
def encode_datapart(data: dict[str, Any]) -> genai_types.Part:
    """A genai Part whose outgoing A2A conversion becomes a real a2a
    DataPart(data=data) — the orchestrator's `find_datapart` decodes it. Uses the
    ADK tag/mime envelope, so no import of the orchestrator package is needed."""
    payload = a2a_types.DataPart(data=data).model_dump_json(by_alias=True, exclude_none=True)
    return genai_types.Part(
        inline_data=genai_types.Blob(
            data=A2A_DATA_PART_START_TAG + payload.encode("utf-8") + A2A_DATA_PART_END_TAG,
            mime_type=A2A_DATA_PART_TEXT_MIME_TYPE,
        )
    )


def decode_datapart(part: genai_types.Part) -> dict[str, Any] | None:
    """Inverse of `encode_datapart` — mirror of the orchestrator's
    `a2a_datapart.decode_datapart` (same envelope, no orchestrator import, B3).
    The leaf needs it to read the INBOUND `{query_params, profile_in}` DataPart
    the a2a→genai conversion re-wraps onto `user_content`."""
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
    """The MOST RECENT decodable DataPart among `parts`, or None — silent
    no-op, never a crash (mirror of the orchestrator's
    `a2a_datapart.find_datapart`).

    S-G5 root-cause fix, live-verified 2026-07-23: `tool_context.user_content
    .parts` on THIS side could carry SEVERAL DataParts — at the time, the
    inbound A2A message replayed the whole conversation (every prior turn's
    snapshot; n_parts grew turn over turn). Returning the FIRST match — the
    old behavior — silently pinned every profile-driven bridge (amenities,
    geo context, pagination) to turn 1's stale snapshot forever; only
    `search_cursor` (monotonically advancing, never coincidentally equal to
    turn 1's value) made the bug visible.

    Latency audit 2026-07-28: the concierge's `StatelessLeafLeg` now sends
    ONLY the current turn's user event (one snapshot), and the leaf itself
    runs `include_contents='none'`. Most-recent-wins stays: it is correct on
    one part, and it keeps this side safe against any OTHER A2A caller that
    still replays history."""
    found: dict[str, Any] | None = None
    for part in parts or []:
        decoded = decode_datapart(part)
        if decoded is not None:
            found = decoded
    return found


def read_profile_in(tool_context: Any) -> dict[str, Any]:
    """The inbound `profile_in` dict riding `tool_context.user_content` (the
    a2a→genai conversion re-wraps the orchestrator's DataPart onto it) — {}
    when missing/undecodable, never a crash. S-G5: the shared reader behind
    the deterministic profile→tool-args bridges (`geocode_tool.
    inject_profile_geo_context`, `inject_pagination_offset` below) — same
    decode as `equipment_ids._profile_amenities`, generalized to the whole
    dict instead of just `.amenities`."""
    content = getattr(tool_context, "user_content", None)
    parts = getattr(content, "parts", None) if content is not None else None
    data = find_datapart(parts)
    if isinstance(data, dict):
        profile = data.get("profile_in")
        if isinstance(profile, dict):
            return profile
    return {}


def inject_verified_named_hotel(tool: Any, args: dict, tool_context: Any) -> None:
    """A carried hotel identity uses the city key returned by that same MCP.

    Human municipality names and MCP market slugs need not be interchangeable.
    A new hotel/destination is not supplied this carried identity by the spine.
    """
    if getattr(tool, "name", "") != "find_hotel_by_name":
        return
    content = getattr(tool_context, "user_content", None)
    data = find_datapart(getattr(content, "parts", None)) or {}
    known = (data.get("query_params") or {}).get("named_hotel")
    if not isinstance(known, dict) or known.get("source") != "mcp_name_lookup":
        return
    if str(args.get("name") or "").casefold() != str(known.get("name") or "").casefold():
        return
    city = known.get("city_name")
    if isinstance(city, str) and city:
        args["cityName"] = city


# --- display normalization (mirrors b2c_concierge.inline_tools shape, S07) -------------------
def _flatten_amenities(raw: Any) -> list[str]:
    names: list[str] = []
    for item in raw or []:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
        elif isinstance(item, str):
            names.append(item)
    return names


def _format_price_eur_cents(cents: Any) -> str | None:
    """`priceEuro` is EUR cents (MCP_B2C) → `€X.XX`. Consistent with S07."""
    if cents is None:
        return None
    try:
        return f"€{float(cents) / 100:.2f}"
    except (TypeError, ValueError):
        return None


def _price_eur_cents(cents: Any) -> int | None:
    """S-CX3a: the same `priceEuro`, kept NUMERIC on the card. Until now the
    `€X.XX` display string was the ONLY survivor of normalization (audit CX
    2026-07-24, gap G-b2), so nothing downstream could compare a price to the
    client's budget — which every step of the price-floor chain needs
    (budget-proximity re-rank S-CX3b, over-budget gap S-CX3c)."""
    if cents is None:
        return None
    try:
        return round(float(cents))
    except (TypeError, ValueError):
        return None


def _hhmm(hour: Any, minute: Any) -> str | None:
    if hour is None:
        return None
    try:
        return f"{int(hour):02d}:{int(minute or 0):02d}"
    except (TypeError, ValueError):
        return None


def _hhmm_from_total(total_minutes: Any) -> str | None:
    """S-G6: the inverse of a minutes-of-day int (0-1439) back to "HH:MM" —
    used to recover the EXACT requested timeslot bound after the before_tool
    callback has already rounded `args["timeSlot"]` to whole hours for MCP."""
    if not isinstance(total_minutes, int) or isinstance(total_minutes, bool):
        return None
    if not 0 <= total_minutes < 24 * 60:
        return None
    hour, minute = divmod(total_minutes, 60)
    return f"{hour:02d}:{minute:02d}"


# An exact clock window (start/end minutes-of-day, site covering rule) or a
# daypart name (soft overlap rule) — see b2c_common.timeslot.
Window = tuple[int | None, int | None] | str


def _offer_matches(offer: dict[str, Any], window: Window) -> bool:
    if isinstance(window, str):
        return slot_overlaps_daypart(offer.get("startHour"), offer.get("endHour"), window)
    return _offer_covers_window(offer, window[0], window[1])


def _offer_covers_window(
    offer: dict[str, Any], start_total: int | None, end_total: int | None
) -> bool:
    """mcp-dayuse#4/#8: the site rule, shared with the concierge's
    `guard_window_match` (`b2c_common.slot_covers_window`) — the offer
    CONTAINS the requested window, in whole hours. It used to be the
    opposite (offer inside the window): five 08–14 offers answered "no
    offer covers 12h–13h exactly", and 6h–16h showed offers the site does
    not."""
    return slot_covers_window(offer.get("startHour"), offer.get("endHour"), start_total, end_total)


def _first(*values: Any) -> Any:
    """First non-None value — unlike `a or b`, preserves a legit falsy id (0)."""
    for value in values:
        if value is not None:
            return value
    return None


def positive_budget(value: Any) -> float | None:
    """A search_offers `priceRangeMax` coerced to a positive float, else None.
    The args are model-generated (untrusted): never persist a garbage or a
    non-positive (0 / negative) budget. Public (like `party_count` below):
    shared with `budget_injection.py` so the carryover and the capture can
    never disagree on what counts as a valid budget."""
    if isinstance(value, bool):
        return None  # bool is an int subclass — float(True) == 1.0 would slip through
    try:
        budget = float(value)
    except (TypeError, ValueError):
        return None
    return budget if budget > 0 else None


def _budget_timeslot_from_args(args: dict[str, Any]) -> dict[str, Any]:
    """The budget / time-slot the model sent search_offers, in the orchestrator's
    profile schema (`budget_max` float, `timeslot_start`/`timeslot_end` "HH:MM").
    Only-when-present: an absent/garbage value simply yields no key, never a wrong
    one. `priceRangeMin` is intentionally NOT mapped — it genuinely narrows the
    MCP search but the concierge profile has no budget-min field (never invent
    one). A one-sided time-slot (only startHour, or only endHour) is kept as-is;
    the concierge handles start_only/end_only modes."""
    captured: dict[str, Any] = {}
    budget_max = positive_budget(args.get("priceRangeMax"))
    if budget_max is not None:
        captured["budget_max"] = budget_max
    time_slot = args.get("timeSlot")
    if isinstance(time_slot, dict):
        start = _hhmm(time_slot.get("startHour"), 0)
        end = _hhmm(time_slot.get("endHour"), 0)
        if start:
            captured["timeslot_start"] = start
        if end:
            captured["timeslot_end"] = end
    return captured


# P0-1 party-size limits. A count this large is a data-entry slip, not a
# booking; refusing it here keeps a fat-fingered "200 adults" from coming back
# as what looks like real empty inventory.
_MAX_PARTY = 30


def party_count(value: Any) -> int | None:
    """A usable party count, or None. Accepts an int or a clean integral string
    (the model sometimes sends `"2"`); rejects bools, fractional floats,
    negatives and absurd sizes. 0 is returned as 0 — meaningful for `children`
    ("adults only"), rejected for `adults` by the callers, since a search for
    zero adults is not a search. Shared with `occupancy.py` so the carryover and
    the capture can never disagree on what counts as a valid party size."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        count = value
    elif isinstance(value, float):
        if value != int(value):
            return None
        count = int(value)
    elif isinstance(value, str):
        try:
            count = int(value.strip())
        except (ValueError, AttributeError):
            return None
    else:
        return None
    if count < 0 or count > _MAX_PARTY:
        return None
    return count


def occupancy_from_args(args: dict[str, Any]) -> dict[str, int]:
    """The party size the model actually sent search_offers, in the
    orchestrator's profile schema. Same only-when-present contract as
    `_budget_timeslot_from_args`: an absent or garbage value yields no key,
    never a wrong one. `adults=0` is dropped (not a search); `children=0` is
    kept ("adults only" is a real statement, distinct from saying nothing)."""
    captured: dict[str, int] = {}
    for name in ("adults", "children"):
        count = party_count(args.get(name))
        if count is None or (name == "adults" and count == 0):
            continue
        captured[name] = count
    return captured


def _stamp_distances(
    results: list[dict[str, Any]], origin: dict[str, Any] | None
) -> None:
    """A8-a instrumentation: set `distance_km` on every card that has coordinates,
    measured from the resolved anchor. In-place; a card without coords is left as-is
    (never a fabricated distance)."""
    if not origin:
        return
    olat, olon = origin.get("latitude"), origin.get("longitude")
    if olat is None or olon is None:
        return
    for card in results:
        clat, clon = card.get("latitude"), card.get("longitude")
        if clat is not None and clon is not None:
            card["distance_km"] = round(haversine_km(olat, olon, clat, clon), 1)


def _stamp_hotel_currency_price(
    card: dict[str, Any], best: dict[str, Any], hotel: dict[str, Any]
) -> None:
    """The SAME offer's price in the hotel's own currency, next to the EUR one
    the card displays by default. The concierge swaps it in when the user asked
    for the hotel's currency (it never converts: MCP sends both, as indexed)."""
    fields = hotel_currency_price(best, hotel)
    original = fields.pop("hotel_original_price", None)
    card.update(fields)
    slot = (card.get("timeslots") or [None])[0]
    if original is not None and isinstance(slot, dict):
        slot["hotel_original_price"] = original


def _best_offer(
    offers: list[dict[str, Any]], hotel: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Cheapest offer by the price the customer is SHOWN (`display_price_euro`:
    with or without booking fees, per the hotel's own setting)."""
    priced = [
        o for o in offers if isinstance(o, dict) and display_price_euro(o, hotel) is not None
    ]
    if priced:
        return min(priced, key=lambda o: display_price_euro(o, hotel))
    return offers[0] if offers and isinstance(offers[0], dict) else None


# Empirically verified 2026-07-20 (no documented constant in MCP_B2C or the
# main site's own code): the production Next.js site serves hotel photos at
# static.dayuse.com/<mainPhotoNormal path> — confirmed live for hotel 22293
# (Villa Paris Orly), same path suffix MCP_B2C returns for the same hotel.
# The widget's host allowlist (isDayuseHost, agent-usa security.js) already
# accepts any *.dayuse.com subdomain, so this needs no frontend change.
_PHOTO_BASE_URL = "https://static.dayuse.com"


def _photo_url(main_photo_normal: Any) -> str | None:
    if not isinstance(main_photo_normal, str) or not main_photo_normal.startswith("/"):
        return None
    return f"{_PHOTO_BASE_URL}{main_photo_normal}"


def normalize_hotel(
    hotel: dict[str, Any], exact_window: Window | None = None
) -> dict[str, Any]:
    """One compact hotel card from an MCP_B2C hotel dict (camelCase). Only the
    fields a booking decision / a card needs — never an invented booking link,
    but `mainPhotoNormal` IS resolved to a real photo URL (see `_photo_url`).

    S-G6 (A4-c): `exact_window` (start/end minutes-of-day), when given,
    restricts the offers considered for `_best_offer`/`timeslots` to those
    that fit ENTIRELY inside it — MCP itself was only sent the floored/ceiled
    HOUR window (its own schema has no minute fields), so a hotel whose only
    offers spill outside the true sub-hour ask must not display one."""
    hotel_id = _first(hotel.get("hotelId"), hotel.get("id"))
    card: dict[str, Any] = {
        "id": hotel_id,
        "hotel_id": hotel_id,
        "name": hotel.get("name"),
        "city": hotel.get("cityName") or hotel.get("city"),
        "country": hotel.get("countryName") or hotel.get("country"),
        "stars": hotel.get("starRating"),
        "rating": hotel.get("globalAverageRating"),
        # S-CX3a: the review count behind that average — MCP_B2C sends it as
        # `totalReview` on the identity block every tool output shares
        # (`HotelIdentityDto`, so search_offers AND get_hotel_details carry it).
        # Needed to shrink a 5.0-from-2-reviews toward the market prior before
        # any quality floor trusts it (S-CX3b); raw pass-through like `rating`.
        "rating_count": hotel.get("totalReview"),
        "amenities": _flatten_amenities(hotel.get("amenities")),
    }
    # S-CX3a: `score` — MCP_B2C's OWN composite relevance score, the order
    # `results` already arrives in (server-side `rankHotels`, same weighting as
    # the ES function_score). Probed live 2026-07-27: present on every
    # search_offers hotel, absent from get_hotel_details (search-only).
    # It is NOT a pure quality signal — SCORING_WEIGHTS is availability .30 /
    # quality .25 / commission .20 / rpmV2 .15 / tier .10, so 35 % is already
    # commercial. Kept because any re-rank (S-CX3b) must be expressed as a
    # bounded modifier OF this baseline rather than a rival ranking invented
    # from a 2-10-review average; a consumer of it owes the double-counting
    # question (a budget-proximity term multiplied onto a score that already
    # contains commission monetizes the same click twice).
    score = _finite_float(hotel.get("score"))
    if score is not None:
        card["relevance_score"] = score
    # Coordinates the MCP returns per hotel (probed live 2026-07-23: `lat`/`lon`).
    # Kept on the card so the shortlist becomes verifiable (A8-a) — distance_km is
    # stamped from the search anchor in capture_after_tool.
    lat, lon = _coord(hotel.get("lat")), _coord(hotel.get("lon"))
    if lat is not None and lon is not None:
        card["latitude"] = lat
        card["longitude"] = lon
    photo = _photo_url(hotel.get("mainPhotoNormal"))
    if photo:
        card["image_urls"] = [photo]
    # The widget resolves the hotel's market from an ISO alpha-2 `country_code`
    # (a full `country` name never matches its ISO-keyed table). search_offers
    # STILL doesn't send one: countryName + slug only, probed live 2026-07-20
    # and re-probed 2026-08-28 (0 of 201 hotels across 21 markets carried a
    # countryCode — UX6 audit, reports/AUDIT-MAPPINGS-2026-08-28.md). Keep the
    # preference so a server-provided code wins the day it appears.
    country_code = _iso_alpha2(hotel.get("countryCode"))
    if country_code:
        card["country_code"] = country_code
    # S-G12: the hotel-page link, built ONLY from the server's own ES `slug`
    # (sent per hotel, probed live 2026-07-23) + the destination market table
    # (b2c_common) — never slugified from the display name (the prod defect:
    # LLM-invented "a-roport"/"eurohotel" slugs on the wrong domain). None →
    # the card honestly has no link.
    url = build_hotel_page_url(
        hotel.get("slug"), hotel.get("countryCode"), hotel.get("countryName") or hotel.get("country")
    )
    if url:
        card["url"] = url
    # S-G7: the hotel's own local currency (display-only, see `_iso_currency`) —
    # `search_offers` sends this directly per hotel (probed live 2026-07-23),
    # unlike country_code above which it never sends.
    currency_code = _iso_currency(hotel.get("currencyCode"))
    if currency_code:
        card["currency_code"] = currency_code
    offers = hotel.get("offers") or []
    if exact_window is not None:
        offers = [o for o in offers if isinstance(o, dict) and _offer_matches(o, exact_window)]
    best = _best_offer(offers, hotel)
    if best:
        shown_price = display_price_euro(best, hotel)
        price = _format_price_eur_cents(shown_price)
        if price:
            card["price"] = price
        cents = _price_eur_cents(shown_price)
        if cents is not None:
            card["price_eur_cents"] = cents
        start, end = _hhmm(best.get("startHour"), best.get("startMinute")), _hhmm(
            best.get("endHour"), best.get("endMinute")
        )
        if start and end:
            slot: dict[str, Any] = {"start": start, "end": end}
            # S-CX8: the night rate this day-use price undercuts, in EUROS on the
            # slot — the exact shape the widget's `computeNightDiscount` has
            # always read (`slot.original_price`, compared against the parsed
            # euro price). Nothing ever filled it, so the carousel's "-33%" badge
            # was dead code in production; MCP exposed `originalPriceEuro`
            # (EUR cents, 98.6% of offers) on 2026-07-28 and it finally can be.
            # Only when the night rate is really higher: a "-0%" badge would be
            # a claim we cannot make.
            original_cents = _price_eur_cents(best.get("originalPriceEuro"))
            if original_cents is not None and cents is not None and original_cents > cents > 0:
                slot["original_price"] = round(original_cents / 100, 2)
            card["timeslots"] = [slot]
        _stamp_hotel_currency_price(card, best, hotel)
        # S-CX5: the IDENTITY of the offer this card prices — `ratePlanUuid` is
        # the booking tunnel's own `offerId` (MCP_B2C generate_booking_link
        # schema) and `availabilityDate` the day it is bookable on. Both come
        # from the SAME `best` dict as the price and the time slot above, so a
        # later booking step can reuse this exact offer instead of re-deriving
        # one from a fresh lookup — the prod defect of 2026-07-27, where a card
        # priced at €87 for 11:00-19:00 tomorrow produced a link for €90 /
        # 17:00-23:00 / today. Only-when-present: a card without them honestly
        # has no reusable offer, and the booking path falls back to a lookup.
        offer_id = best.get("ratePlanUuid")
        if isinstance(offer_id, str) and offer_id.strip():
            card["offer_id"] = offer_id.strip()
        offer_date = best.get("availabilityDate")
        if isinstance(offer_date, str) and offer_date.strip():
            card["offer_date"] = offer_date.strip()
        # P0-1: how many people this priced offer actually sleeps. From the same
        # `best` dict as the price above, so the numbers on a card always
        # describe ONE offer. Snake_case on the card (`children_capacity`) —
        # MCP sends `capacity`/`childrenCapacity`. Without these two the
        # response disclosed nothing about occupancy even when MCP had filtered
        # on it, so "for 2 adults and 1 child" was unverifiable from the outside.
        for card_key, mcp_key in (
            ("capacity", "capacity"),
            ("children_capacity", "childrenCapacity"),
        ):
            value = best.get(mcp_key)
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            if value >= 0:
                card[card_key] = value
    return card


def normalize_search_results(
    structured: Any,
    exclude_ids: set[Any] | None = None,
    exact_window: Window | None = None,
) -> list[dict[str, Any]]:
    """Top-5 compact cards from a tool's structuredContent. Handles the
    `search_offers` envelope (`{"results": [...]}`, confirmed live) and the
    `find_hotel_by_name` single-hotel shape (`{"hotel": {...}}`); tolerant of a
    `hotels` key just in case (the server owns the envelope).

    S-G5: `exclude_ids` (the profile's accumulated `shown_hotel_ids`) is
    filtered out BEFORE the top-5 cut — the belt-and-suspenders safety net for
    "other options" alongside the `from`-offset pagination bridge
    (`inject_pagination_offset`): the server's own offset advances the page,
    this filter catches any overlap the offset math didn't (a page-size change
    between turns, ranking drift). `find_hotel_by_name` never passes
    `exclude_ids` — a named lookup must never be hidden as "already shown".

    S-G6 (A4-c): `exact_window`, when given, drops a hotel ENTIRELY when none
    of its offers covers the requested window (see `_offer_covers_window`) —
    MCP's own `timeSlot` filter keeps any OVERLAPPING offer, so a hotel whose
    only offer is 17:00-22:00 comes back for "22h-23h". `find_hotel_by_name` never passes
    `exact_window` either — a name lookup is not bound to a search's time."""
    if not isinstance(structured, dict):
        return []
    items = structured.get("results")
    if items is None:
        items = structured.get("hotels")
    if items is None:
        single = structured.get("hotel")
        items = [single] if isinstance(single, dict) else []
    hotels: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        if exact_window is not None:
            fits_any = any(
                isinstance(o, dict) and _offer_matches(o, exact_window)
                for o in (item.get("offers") or [])
            )
            if not fits_any:
                continue
        hotels.append(normalize_hotel(item, exact_window))
    if exclude_ids:
        hotels = [h for h in hotels if h.get("hotel_id") not in exclude_ids]
    return hotels[:MAX_RESULTS]


def _parse_content_text(tool_response: dict[str, Any]) -> dict[str, Any] | None:
    """Fallback when `structuredContent` is absent: the first JSON-parsable
    `content[].text` block (the MCP text mirror of the structured payload)."""
    for block in tool_response.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            try:
                parsed = json.loads(block["text"])
            except (ValueError, TypeError):
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def read_structured_payload(tool_response: Any) -> dict[str, Any] | None:
    """An MCP tool result's payload: `structuredContent`, else the text mirror.
    Public (S-CX6) so the next-day probe in datetime_resolver reads a tool
    result EXACTLY the way capture_after_tool does — the two must never
    disagree about what "this response is empty" means."""
    if not isinstance(tool_response, dict):
        return None
    structured = tool_response.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    return _parse_content_text(tool_response)


# --- callbacks ------------------------------------------------------------------------------
# P0-2 fix 4. "Around the Champs-Élysées" must not mean "anywhere in greater
# Paris". MCP_B2C's `search_offers` takes `radiusKm` (default **20**), so until
# now a landmark anchor and a city anchor searched an identical 20 km disc — the
# geocode could resolve the avenue to within 250 m and the results would still
# come back from La Défense (7 km) and Orly (13 km). That is why the audit
# measured only 18-24 % of returned hotels inside the landmark radius while
# `resolved_country_code` was already at 72-78 %: the two halves of the promise
# fail independently, and fixing the geocode alone does not move this one.
#
# 3 km is the product intent already encoded in `evals/datasets/b2c-geo-poi.jsonl`:
# 13 of its 17 `hotels_within_km` assertions use 3, the wider ones being
# genuinely out-of-town anchors (Disneyland 10, JFK 10). A 3 km search satisfies
# every one of them, and 3 km around an urban landmark is what a customer means
# by "around".
_POI_RADIUS_KM = 3.0


def inject_landmark_radius(tool: Any, args: dict[str, Any], tool_context: Any) -> dict | None:
    """`before_tool_callback`: the ONLY writer of search_offers' `radiusKm`.

    Tightens the search disc to `_POI_RADIUS_KM` when THIS turn's anchor is a
    landmark/POI, and otherwise leaves the key absent so MCP applies its own
    20 km city default. Same doctrine as `from` and `hotelEquipmentIds`: the
    model is never taught this parameter and any value it invents is dropped —
    a radius is a filter, and the LLM never owns a filter value.

    Reads the anchor the geocode tool already stashed this turn
    (`_STATE_ANCHOR_KEY`, written by `capture_after_tool`'s GEOCODE branch), so
    it needs no new plumbing and cannot fire on a city search. It deliberately
    does NOT read `_STATE_DISTANCE_ORIGIN_KEY`, which carries the same `type`
    but is only written in the SEARCH branch — i.e. after `search_offers` has
    already run, far too late for a before-tool callback. Reading that one is
    silent no-op territory: everything type-checks and the radius is simply
    never applied.
    `gps` anchors are deliberately NOT tightened here: "near me" has its own
    expectations and changing it is not part of the POI bug.

    Scarcity note: a tighter disc can legitimately return nothing where the 20 km
    one returned something. That is a HONEST empty, and the existing
    empty-shortlist score plus the S-CX2 false-scarcity guard are what make it
    visible — but if `min_hotels` drops on the geo dataset, this constant is the
    first thing to revisit."""
    if getattr(tool, "name", "") != "search_offers":
        return None
    args.pop("radiusKm", None)
    origin = tool_context.state.get(_STATE_ANCHOR_KEY)
    if isinstance(read_profile_in(tool_context).get("search_location_request"), dict):
        if not isinstance(origin, dict):
            return {"ok": False, "error": "geocode_required",
                    "message": "Call geocode_location successfully before search_offers."}
        # Coordinates are geocoder-owned. Model copies (including coordinates
        # remembered from the previous destination) have no authority here.
        args["lat"] = origin["latitude"]
        args["lon"] = origin["longitude"]
    anchor_type = origin.get("type") if isinstance(origin, dict) else None
    if anchor_type == "poi":
        args["radiusKm"] = _POI_RADIUS_KM
    # Content-free counter (flags only), and the audit's P0-3 ask: which geo tier
    # a turn actually took is otherwise invisible. It is also what caught the
    # first version of this callback reading the wrong state key — it logged
    # anchor=none on every landmark turn while everything still type-checked.
    _metrics_logger.info(
        "dayuse_metric=landmark_radius agent=b2c_hotel_search anchor=%s applied=%d",
        anchor_type or "none",
        int("radiusKm" in args),
    )
    return None


def inject_pagination_offset(tool: Any, args: dict[str, Any], tool_context: Any) -> None:
    """`before_tool_callback` (S-G5, A7): the ONLY writer of search_offers'
    `from` — the model is never taught pagination (there is nothing in the
    message to extract; whether this is page 2 lives entirely in
    `profile_in.search_cursor`, S-G1's `advance_search_cursor`). Live-probed
    2026-07-23 against MCP_B2C staging: `search_offers` accepts `from`
    (offset, default 0) / `size` (page size, default 10) and an
    offset advanced by a full page returns genuinely disjoint hotel ids —
    real server-side pagination, no `excludeHotelIds`-style param exists
    (confirmed: an unrecognized key is a hard schema-validation error). So the
    `from` offset is the PRIMARY pagination driver; `shown_hotel_ids`
    (normalize_search_results, above) stays a client-side safety net for
    misaligned page boundaries. Any `from` the model itself supplied is
    unconditionally overwritten — same doctrine as `hotelEquipmentIds`: the
    LLM never owns a filter/paging value.

    ⚠️ `total` and `has_more` are computed BEFORE the bookability check, so
    neither is a count of what a customer can actually book (re-probed live
    2026-07-29: Los Angeles `total=110, has_more=true` at `from=80` while the
    real surviving pool was ~22 hotels and `from=160` came back empty; Paris
    `total=612, results=[]` on every offset once the day's cutoffs passed).
    Never paginate on `has_more` alone, and never report `total` as availability.

    ⚠️ `size` is NOT safely raisable (re-probed live 2026-07-27, correcting the
    "max 50" this docstring used to claim): `size` ≥ 16 comes back as an EMPTY
    structuredContent — no `results`, no `total`, and NO `isError`. A caller
    that raised the page size would therefore read a silent ZERO and report
    "no offers" on a market with 521 of them: the false-scarcity failure mode
    of audit CX F2, from a different cause. Nothing sets `size` today (server
    default 10, which is 2× MAX_RESULTS) — keep it that way unless the cliff
    is fixed server-side."""
    if getattr(tool, "name", "") != "search_offers":
        return None
    profile_in = read_profile_in(tool_context)
    cursor = profile_in.get("search_cursor") or 0
    try:
        cursor = int(cursor)
    except (TypeError, ValueError):
        cursor = 0
    args["from"] = max(cursor, 0) * MAX_RESULTS
    return None


def _apply_date_fallback(tool_context: Any, stashed: dict[str, Any]) -> None:
    """Book-keeping once the D+1 swap is decided (S-CX6).

    Two writes, both required. The turn's search date becomes the day actually
    on screen — keeping `cutoff_fallback_from` so the answer is FORCED to say
    which day it is showing (offers presented as today's when they are
    tomorrow's would be worse than the dead end it replaces). And the resolved
    date is persisted with a `cutoff_fallback` provenance, so the profile
    carries the new day forward: without it the next turn ("cheaper", "with a
    pool") would re-search today and die on the very same cutoff."""
    searched = stashed.get("searched_date")
    offered = stashed.get("offered_date")
    if not isinstance(offered, str) or not offered:
        return
    search_date: dict[str, Any] = {"date": offered, "same_day": False}
    if isinstance(searched, str) and searched:
        search_date["cutoff_fallback_from"] = searched
    tool_context.state[STATE_SEARCH_DATE_KEY] = search_date
    date_reference: dict[str, Any] = {"resolved_from": "cutoff_fallback"}
    previous = tool_context.state.get(STATE_RESOLVED_DATE_KEY)
    if isinstance(previous, dict):
        client_tz = (previous.get("date_reference") or {}).get("client_tz")
        if isinstance(client_tz, str) and client_tz:
            date_reference["client_tz"] = client_tz
    tool_context.state[STATE_RESOLVED_DATE_KEY] = {
        "date": offered,
        "date_reference": date_reference,
    }


def record_guards_fired(tool_context: Any, names: Iterable[str]) -> None:
    """Merge deterministic guard names into the turn's OBS3 set — the SINGLE
    writer of `_STATE_GUARDS_KEY`, so both producers share one semantics
    (accumulate across callbacks, dedupe, stay ordered).

    Two producers, two shapes. `geocode_location` returns its own
    `guards_fired` list in the tool response, folded in by `capture_after_tool`
    below. `datetime_resolver.resolve_search_date` is a BEFORE-tool callback:
    there is no response to hang a key on, so it fills a local accumulator and
    calls this directly. Either way `emit_search_datapart` finds them in state.

    RGPD: a guard NAME and nothing else — never the date, the place or the
    message that made it fire."""
    fired = [str(n) for n in names if n]
    if not fired:
        return
    previous = tool_context.state.get(_STATE_GUARDS_KEY) or []
    tool_context.state[_STATE_GUARDS_KEY] = sorted({*(str(p) for p in previous), *fired})


def _record_fallback(tool_context: Any, name: str) -> None:
    previous = tool_context.state.get(_STATE_FALLBACKS_KEY) or []
    tool_context.state[_STATE_FALLBACKS_KEY] = sorted({*previous, name})


def _record_mcp_error(
    tool_context: Any, tool_name: str, args: dict[str, Any], tool_response: dict[str, Any]
) -> None:
    kind = classify_mcp_error(tool_response) or "failed"
    if kind == "not_found" and tool_name == "find_hotel_by_name":
        envelope = (tool_response.get("structuredContent") or {}).get("error") or {}
        query = envelope.get("query") or args.get("name")
        if isinstance(query, str) and query.strip():
            tool_context.state[_STATE_NAMED_NOT_FOUND_KEY] = query.strip()
        _record_fallback(tool_context, "named_hotel_not_found")
        return
    _record_fallback(tool_context, "mcp_error")
    if tool_context.state.get(_STATE_MCP_ERROR_KEY) != "failed":
        tool_context.state[_STATE_MCP_ERROR_KEY] = "failed" if kind == "failed" else "rejected"


def capture_after_tool(
    tool: Any, args: dict[str, Any], tool_context: Any, tool_response: Any
) -> dict[str, Any] | None:
    """`after_tool_callback` (placed LAST, after mcp_circuit_after_tool so the
    breaker still observes the real outcome). Two jobs:
      - geocode_location → stash its `profile_delta` (no truncation).
      - search_offers / find_hotel_by_name → normalize + stash the top-5 results;
        for search_offers ALSO return the compact payload as the tool result the
        MODEL ingests (the ~24k-token bloat never reaches the model).
    A tool failure returns None (the model must see the real error verbatim)."""
    name = getattr(tool, "name", "") or ""

    if name == "geocode_location":
        # Guards are recorded on EVERY outcome, not just the successful ones: a
        # guard that fired and then made the turn fail honestly is exactly what
        # OBS3 needs to see.
        if isinstance(tool_response, dict):
            fired = tool_response.get("guards_fired")
            if isinstance(fired, list):
                record_guards_fired(tool_context, fired)
        if isinstance(tool_response, dict) and tool_response.get("ok"):
            resolved_delta = dict(tool_response.get("profile_delta") or {})
            tool_context.state["temp:resolved_search_location"] = dict(tool_response)
            request = read_profile_in(tool_context).get("search_location_request")
            if isinstance(request, dict):
                # Only a successful resolution may promote the requested
                # destination. Explicitly cleared areas must clear Redis too.
                if request.get("city"):
                    resolved_delta["last_city"] = request["city"]
                for key in ("zone", "metro"):
                    resolved_delta[key] = request.get(key)
            if resolved_delta:
                tool_context.state[_STATE_DELTA_KEY] = resolved_delta
            country_code = _iso_alpha2(tool_response.get("country_code"))
            if country_code:
                tool_context.state[_STATE_COUNTRY_KEY] = country_code
            # The resolved place is the distance origin for this search's cards.
            a_lat, a_lon = _coord(tool_response.get("latitude")), _coord(tool_response.get("longitude"))
            if a_lat is not None and a_lon is not None:
                tool_context.state[_STATE_ANCHOR_KEY] = {
                    "latitude": a_lat,
                    "longitude": a_lon,
                    "label": tool_response.get("resolved_place"),
                    "type": tool_response.get("distance_origin_type") or "city_centroid",
                }
        elif isinstance(tool_response, dict) and tool_response.get("error") == "geocode_ambiguous":
            # 2026-08-26: a clarify carries a profile delta too, and it has to be
            # stashed like the ok-path's — otherwise the subject of the question
            # dies with the turn. Verified in prod: asked "gare de lyon — which
            # city?", answered "paris", and the search ran on the bare Paris
            # centroid because the zone was never persisted. The re-injection
            # side already existed (`inject_profile_geo_context` refills `zone`
            # from the profile); only the write was missing.
            delta = tool_response.get("profile_delta")
            if isinstance(delta, dict) and delta:
                previous = tool_context.state.get(_STATE_DELTA_KEY) or {}
                tool_context.state[_STATE_DELTA_KEY] = {**previous, **delta}
            # S-G10 (D3): remember the clarify question — emit_search_datapart
            # turns it into a deterministic `requires_clarification` flag when
            # no search ends up running this turn.
            question = (tool_response.get("diagnostics") or {}).get("question")
            if isinstance(question, str) and question.strip():
                tool_context.state[_STATE_CLARIFY_QUESTION_KEY] = question.strip()
        elif isinstance(tool_response, dict) and tool_response.get("error") in {"geocode_echo_mismatch", "no_geocodable_location"}:
            # A rejected place is not a hotel-search outage. End this bounded
            # lookup with a clarification instead of retrying the same place.
            language = _profile_language(tool_context)
            questions = {
                "en": "I couldn't verify that location. Which city or nearby address should I use?",
                "fr": "Je n'ai pas pu vérifier ce lieu. Quelle ville ou adresse à proximité dois-je utiliser ?",
                "es": "No he podido verificar ese lugar. ¿Qué ciudad o dirección cercana debo usar?",
                "it": "Non ho potuto verificare quel luogo. Quale città o indirizzo vicino devo usare?",
                "de": "Ich konnte diesen Ort nicht verifizieren. Welche Stadt oder nahe Adresse soll ich verwenden?",
                "pt": "Não consegui verificar esse local. Que cidade ou endereço próximo devo usar?",
                "nl": "Ik kon die locatie niet verifiëren. Welke stad of nabijgelegen adres moet ik gebruiken?",
            }
            tool_context.state[_STATE_CLARIFY_QUESTION_KEY] = questions.get(language, questions["en"])
        return None

    if name not in _TARGET_TOOLS or not isinstance(tool_response, dict):
        return None
    if tool_response.get("error") == "mcp_circuit_open":
        # S-CX2: the breaker short-circuited an MCP search call — remember it so
        # emit_search_datapart / skip_final_generation degrade deterministically
        # (the model still sees the neutral diagnostic, but its prose no longer
        # decides what the customer reads on this failure).
        tool_context.state[_STATE_SEARCH_UNAVAILABLE_KEY] = True
        _record_fallback(tool_context, "mcp_error")
        tool_context.state[_STATE_MCP_ERROR_KEY] = "failed"
        return None
    if tool_response.get("isError") or tool_response.get("ok") is False:
        _record_mcp_error(tool_context, name, args, tool_response)
        return None  # a real failure — leave it untouched for the model to relay

    structured = read_structured_payload(tool_response)
    if not isinstance(structured, dict):
        return None

    exclude_ids: set[Any] | None = None
    strict_window: Window | None = None
    if name == "search_offers":
        # S-G5 pagination safety net: hotels already shown across earlier turns
        # (accumulated at the profile, S-G1) are filtered out before the top-5
        # cut. A named lookup (find_hotel_by_name) never excludes — see below.
        #
        # S-CX5: ONLY on a pagination turn (`search_cursor > 0`). This filter
        # exists to stop page 2 repeating page 1 — applying it to every search
        # made a refined search hide the hotels the user had just been shown,
        # which is how "book the cheapest" answered with pricier hotels: the
        # five cheapest were on screen, so the search meant to rank them
        # excluded them and returned ranks 6-10 (prod session 2026-07-27).
        # The concierge resets the cursor on any non-pagination search
        # (`profile.reset_search_cursor`), so page 1 always sees the full pool.
        profile_in = read_profile_in(tool_context)
        shown = profile_in.get("shown_hotel_ids")
        try:
            paginating = int(profile_in.get("search_cursor") or 0) > 0
        except (TypeError, ValueError):
            paginating = False
        if paginating and isinstance(shown, list) and shown:
            exclude_ids = set(shown)
        # S-G6 (A4-c): a genuine two-sided exact window (stashed by
        # datetime_resolver.resolve_search_timeslot before MCP only got the
        # floored/ceiled hours) — a one-sided bound is never strict-filtered
        # here (existing "kept as-is" mode, unchanged).
        exact_window_state = tool_context.state.get(STATE_EXACT_WINDOW_KEY)
        if isinstance(exact_window_state, dict):
            start_total, end_total = exact_window_state.get("start_total"), exact_window_state.get(
                "end_total"
            )
            if isinstance(start_total, int) or isinstance(end_total, int):
                strict_window = (
                    start_total if isinstance(start_total, int) else None,
                    end_total if isinstance(end_total, int) else None,
                )
        daypart = tool_context.state.get(STATE_DAYPART_KEY)
        if daypart in DAYPART_HOURS:
            strict_window = daypart
    results = normalize_search_results(structured, exclude_ids, strict_window)
    if name == "find_hotel_by_name" and len(results) == 1:
        hotel = results[0]
        identity = structured.get("hotel") or {}
        tool_context.state["temp:verified_named_hotel"] = {
            "hotel_id": hotel.get("hotel_id"), "name": hotel.get("name"), "source": "mcp_name_lookup",
            "city_name": identity.get("cityName"), "country_code": identity.get("countryCode"),
        }
    timeslot_fallback = False
    if strict_window is not None and not results:
        # The exact-minute filter emptied the set: fall back to the coarser
        # hour-rounded results (never a silent 0) — the outcome text discloses it.
        fallback_results = normalize_search_results(structured, exclude_ids, None)
        if fallback_results:
            results = fallback_results
            timeslot_fallback = True
    # S-CX6: still empty, and the probe found a bookable D+1 next door → serve
    # THAT day instead of a dead end. Placed BEFORE the search_offers block
    # below on purpose: the swapped-in cards must get the same distance /
    # country / applied-amenity stamping as any other card, and the compact
    # payload the model ingests must describe the day it is actually looking at
    # (`structured` is rebound, so resolvedDate/total below follow the swap).
    if name == "search_offers" and not results:
        stashed = tool_context.state.get(STATE_DATE_FALLBACK_KEY)
        payload = stashed.get("payload") if isinstance(stashed, dict) else None
        if isinstance(payload, dict):
            swapped = normalize_search_results(payload, exclude_ids, strict_window)
            if not swapped and strict_window is not None:
                swapped = normalize_search_results(payload, exclude_ids, None)
                timeslot_fallback = bool(swapped)
            if swapped:
                results = swapped
                structured = payload
                _apply_date_fallback(tool_context, stashed)
    if timeslot_fallback:
        tool_context.state[_STATE_TIMESLOT_FALLBACK_KEY] = True
    if name == "search_offers":
        radius = args.get("radiusKm")
        if isinstance(radius, (int, float)) and not isinstance(radius, bool):
            tool_context.state[_STATE_RADIUS_KEY] = radius
        tool_context.state[_STATE_SEARCH_PAGE_KEY] = search_page_from(structured)
        # Distance instrumentation (A8-a): the anchor is the geocode result the
        # model copied into search_offers' lat/lon — prefer the richer stashed
        # anchor (carries a label/type), fall back to the raw args coords.
        origin = tool_context.state.get(_STATE_ANCHOR_KEY)
        if not origin:
            a_lat, a_lon = _coord(args.get("lat")), _coord(args.get("lon"))
            if a_lat is not None and a_lon is not None:
                origin = {"latitude": a_lat, "longitude": a_lon, "label": None, "type": "search_coordinate"}
        if origin and results:
            _stamp_distances(results, origin)
            tool_context.state[_STATE_DISTANCE_ORIGIN_KEY] = origin
        # The search ran at the geocoded coordinates, so the geocoded country is
        # a legitimate attribute of ITS results (a server-sent countryCode always
        # wins via setdefault). find_hotel_by_name is NOT stamped — a name lookup
        # is not bound to the geocoded location.
        search_country = tool_context.state.get(_STATE_COUNTRY_KEY)
        if search_country:
            for card in results:
                card.setdefault("country_code", search_country)
        # Amenities the search was HARD-filtered on are server-guaranteed truths
        # for every returned hotel (search_offers itself sends no amenity list) —
        # stamping them is what lets the concierge's ground-truth block back a
        # "pool" claim instead of hedging it "(non confirmé)". "pet_friendly" →
        # "pet friendly": the claim guard's synonym table only knows the spaced
        # form. find_hotel_by_name is never stamped (a name lookup is not bound
        # to this search's filters).
        applied = tool_context.state.get(STATE_APPLIED_AMENITIES_KEY) or []
        if applied:
            labels = [key.replace("_", " ") for key in applied]
            for card in results:
                existing = card.get("amenities") or []
                card["amenities"] = existing + [lbl for lbl in labels if lbl not in existing]
        # Capture the budget / time-slot the model actually passed search_offers
        # (from the REAL args, not the model's prose) → emit maps it to the
        # profile so the concierge's S12 budget/timeslot guards finally engage.
        # Runs for a 0-result search too (that is exactly when auto-widen needs
        # the budget); a failed search already returned above, so nothing here.
        budget_timeslot = _budget_timeslot_from_args(args)
        if tool_context.state.get(STATE_DAYPART_KEY):
            # The timeSlot sent was the daypart's hours, not a stated window.
            budget_timeslot.pop("timeslot_start", None)
            budget_timeslot.pop("timeslot_end", None)
        # S-G6 (core-e2e-084): `args["timeSlot"]` only holds the floored/ceiled
        # HOUR bounds by the time this after_tool_callback sees it (the
        # before_tool_callback already rewrote it for MCP, which has no minute
        # fields) — the EXACT requested minutes were stashed separately and
        # override the hour-only, minute-forced-to-:00 capture above.
        exact_window_state = tool_context.state.get(STATE_EXACT_WINDOW_KEY)
        if isinstance(exact_window_state, dict):
            start_hhmm = _hhmm_from_total(exact_window_state.get("start_total"))
            end_hhmm = _hhmm_from_total(exact_window_state.get("end_total"))
            if start_hhmm:
                budget_timeslot["timeslot_start"] = start_hhmm
            if end_hhmm:
                budget_timeslot["timeslot_end"] = end_hhmm
        # P0-1: same only-when-present contract, from the SAME real args. The
        # model already emits adults/children ~78% of the turns they are stated;
        # until this capture existed nothing read them, so they never reached
        # the profile and could not survive to the next turn.
        budget_timeslot.update(occupancy_from_args(args))
        if budget_timeslot:
            tool_context.state[_STATE_BUDGET_TIMESLOT_KEY] = budget_timeslot
        # Content-free counter (flags only): lets a live run confirm whether the
        # model extracted a budget/time-slot — including the negation/hallucination
        # trap (has_budget=0 on a search with no budget in the message).
        _metrics_logger.info(
            "dayuse_metric=budget_timeslot agent=b2c_hotel_search has_budget=%d has_timeslot=%d",
            int("budget_max" in budget_timeslot),
            int("timeslot_start" in budget_timeslot or "timeslot_end" in budget_timeslot),
        )
    if name == "search_offers":
        results = order_returned_offers(results, read_profile_in(tool_context).get("search_priority"))
    tool_context.state[_STATE_RESULTS_KEY] = results

    if name != "search_offers":
        return None  # find_hotel_by_name payload is already small: stash only
    # Replace the model's view of the big payload with the compact top-5. The
    # orchestrator gets the FULL structured results from the DataPart, not here.
    return {
        "resolvedDate": structured.get("resolvedDate"),
        "total": structured.get("total"),
        "hotels": results,
    }


def order_returned_offers(results: list[dict], priority: str | None) -> list[dict]:
    """Order this returned page only; never claim catalogue-wide optimality."""
    field = {"price": "price_eur_cents", "distance": "distance_km", "rating": "rating"}.get(priority or "")
    if field is None:
        return results

    def key(hotel: dict) -> tuple[bool, float]:
        value = hotel.get(field)
        if not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(value):
            return (True, 0.0)
        return (False, -float(value) if priority == "rating" else float(value))

    return sorted(results, key=key)


def _op_set(value: Any) -> dict[str, Any]:
    """S-G1 typed-ops envelope for an explicit "set" — the concierge's
    `apply_profile_delta` reducer accepts this identically to a bare value
    (S-G1 retro-compat) for a NON-empty value, and treats it as an
    authoritative replacement (UX1) for the slots that need one.

    `amenities` migrated here in UX1 — the "out of this phase's scope" note
    this docstring used to carry: a filter that can only be added to is a
    filter the user cannot retract. Budget/timeslot stay flat (their
    retraction is a separate, unarbitrated question — see the HANDOFF's
    "budget affiche != budget applique" note)."""
    return {"op": "set", "value": value}


# UX2 (2026-08-27): local copy of the concierge's triage.TEMPLATE_LANGUAGES —
# this leaf is a separate stateless A2A package (decision B3) with no import
# path to b2c_concierge, so this tuple is kept in sync by hand.
_SUPPORTED_LANGUAGES = ("fr", "en", "es", "it", "de", "pt", "nl")


def _profile_language(context: Any) -> str:
    """The conversation's response language (profile_in.language, triage-
    owned) — "en" when absent/unrecognized. S-CX2 (audit CX F3): the leaf's
    code-built texts are normally rewritten by the orchestrator's synthesis,
    but on a synthesis failure they are served VERBATIM — a French customer
    was receiving raw English. UX2 widened this from fr/en to the 7 languages
    the concierge now answers in (see triage.TEMPLATE_LANGUAGES)."""
    language = read_profile_in(context).get("language")
    return language if language in _SUPPORTED_LANGUAGES else "en"


_DATE_FALLBACK_SWAPPED: dict[str, str] = {
    "fr": (
        " Les réservations pour aujourd'hui ({fell_back_from}) sont closes — "
        "ces offres sont celles du {offered}."
    ),
    "en": (
        " Same-day bookings for today ({fell_back_from}) are closed — "
        "these offers are for {offered}."
    ),
    "es": (
        " Las reservas para hoy ({fell_back_from}) están cerradas — estas "
        "ofertas son para el {offered}."
    ),
    "it": (
        " Le prenotazioni per oggi ({fell_back_from}) sono chiuse — queste "
        "offerte sono per il {offered}."
    ),
    "de": (
        " Buchungen für heute ({fell_back_from}) sind bereits geschlossen — "
        "diese Angebote gelten für den {offered}."
    ),
    "pt": (
        " As reservas para hoje ({fell_back_from}) estão encerradas — estas "
        "ofertas são para o dia {offered}."
    ),
    "nl": (
        " Boekingen voor vandaag ({fell_back_from}) zijn gesloten — deze "
        "aanbiedingen gelden voor {offered}."
    ),
}

_DATE_FALLBACK_SAME_DAY: dict[str, str] = {
    "fr": (
        " Recherche effectuée pour aujourd'hui ({offered}) : les réservations "
        "du jour sont déjà closes."
    ),
    "en": (
        " This search was for today ({offered}): same-day bookings are "
        "already closed."
    ),
    "es": (
        " Búsqueda realizada para hoy ({offered}): las reservas del mismo "
        "día ya están cerradas."
    ),
    "it": (
        " Ricerca effettuata per oggi ({offered}): le prenotazioni dello "
        "stesso giorno sono già chiuse."
    ),
    "de": (
        " Suche für heute ({offered}) durchgeführt: Buchungen für den "
        "gleichen Tag sind bereits geschlossen."
    ),
    "pt": (
        " Pesquisa efetuada para hoje ({offered}): as reservas do próprio "
        "dia já estão encerradas."
    ),
    "nl": (
        " Zoekopdracht uitgevoerd voor vandaag ({offered}): boekingen voor "
        "dezelfde dag zijn al gesloten."
    ),
}

_DATE_FALLBACK_PLAIN: dict[str, str] = {
    "fr": " Recherche effectuée pour le {offered}.",
    "en": " Searched for {offered}.",
    "es": " Búsqueda realizada para el {offered}.",
    "it": " Ricerca effettuata per il {offered}.",
    "de": " Suche durchgeführt für den {offered}.",
    "pt": " Pesquisa efetuada para o dia {offered}.",
    "nl": " Zoekopdracht uitgevoerd voor {offered}.",
}


def _date_fallback_line(search_date: Any, language: str, has_results: bool = False) -> str:
    """The honest same-day-cutoff disclosure (S-CX6), or the plain searched-date
    line on a normal turn. Two disclosure shapes: the swap happened (offers for
    another day are on screen — say WHICH day and why), or a same-day search
    stayed empty BECAUSE the booking window closed (say that today's bookings
    are what closed, not that the city has no hotels — the old text sent users
    off widening a zone that had 518 hotels in it).

    "Closed" needs BOTH an empty result and `cutoff_closed` (set by
    `datetime_resolver` only when hotels matched and none was bookable). Keyed
    on `same_day` alone, it was appended to same-day searches WITH bookable
    results — prod 2026-09-23, Singapore at 18h local: 4 cards on screen and a
    reply saying "les réservations du jour sont closes". Over an empty pool it
    would be an invented cause too (the concierge's `date_context_block`
    applies the same rule)."""
    if not isinstance(search_date, dict):
        return ""
    offered, fell_back_from = search_date.get("date"), search_date.get("cutoff_fallback_from")
    if isinstance(fell_back_from, str) and isinstance(offered, str):
        template = _DATE_FALLBACK_SWAPPED.get(language, _DATE_FALLBACK_SWAPPED["en"])
        return template.format(fell_back_from=fell_back_from, offered=offered)
    if (
        not has_results
        and search_date.get("same_day")
        and search_date.get("cutoff_closed")
        and isinstance(offered, str)
    ):
        template = _DATE_FALLBACK_SAME_DAY.get(language, _DATE_FALLBACK_SAME_DAY["en"])
        return template.format(offered=offered)
    if isinstance(offered, str):
        template = _DATE_FALLBACK_PLAIN.get(language, _DATE_FALLBACK_PLAIN["en"])
        return template.format(offered=offered)
    return ""


_OUTCOME_EMPTY: dict[str, str] = {
    "fr": "Aucune offre de jour trouvée pour cette recherche.",
    "en": "No day-use offers found for this search.",
    "es": "No se encontraron ofertas de día para esta búsqueda.",
    "it": "Nessuna offerta per il giorno trovata per questa ricerca.",
    "de": "Keine Tagesangebote für diese Suche gefunden.",
    "pt": "Não foram encontradas ofertas de dia para esta pesquisa.",
    "nl": "Geen dagaanbiedingen gevonden voor deze zoekopdracht.",
}

# mcp-dayuse#4: no count. The cards are one page (MAX_RESULTS) and MCP's
# `total` is counted before bookability, so "5 offres trouvées" read as the
# number of matches; neither number is one.
_OUTCOME_FOUND: dict[str, str] = {
    "fr": "Offres de jour affichées : {names}.",
    "en": "Day-use offers shown: {names}.",
    "es": "Ofertas de día mostradas: {names}.",
    "it": "Offerte per il giorno mostrate: {names}.",
    "de": "Angezeigte Tagesangebote: {names}.",
    "pt": "Ofertas de dia apresentadas: {names}.",
    "nl": "Getoonde dagaanbiedingen: {names}.",
}

def timeslot_window_label(start_total: int | None, end_total: int | None) -> str:
    """The requested window in whole hours, as the site rule reads it."""
    arrival, departure = requested_hours(start_total, end_total)
    if arrival is not None and departure is not None:
        return f"{arrival:02d}:00–{departure:02d}:00"
    if arrival is not None:
        return f"{arrival:02d}:00"
    if departure is not None:
        return f"{departure:02d}:00"
    return ""


def _outcome_text(
    results: list[dict[str, Any]],
    timeslot_fallback: bool = False,
    language: str = "en",
    search_date: Any = None,
    window: str = "",
) -> str:
    """A short, code-built (zero-LLM) grounded outcome line. This becomes the
    orchestrator's `leaf_text` — it re-synthesizes the user-facing answer in the
    user's language from this + the structured results' ground-truth block, so
    this text only needs to be a faithful, compact summary (never invented) —
    localized for the 7 languages the concierge can answer in (S-CX2, widened
    by UX2) because it IS shown verbatim when synthesis fails.

    S-G6 (A4-c): `timeslot_fallback` — set when the exact-minute window would
    have emptied the results entirely and the leaf fell back to the coarser
    hour-rounded set instead of a silent 0 — appends an honest disclosure so
    the synthesis never implies these hotels cover the exact time asked."""
    date_line = _date_fallback_line(search_date, language, has_results=bool(results))
    if not results:
        return _OUTCOME_EMPTY.get(language, _OUTCOME_EMPTY["en"]) + date_line
    names = ", ".join(str(r.get("name")) for r in results if r.get("name"))
    template = _OUTCOME_FOUND.get(language, _OUTCOME_FOUND["en"])
    text = template.format(names=names) + date_line
    if timeslot_fallback:
        text += " " + window_fallback_line(window, language)
    return text


def _state_window_label(state: Any) -> str:
    daypart = state.get(STATE_DAYPART_KEY)
    if daypart in DAYPART_HOURS:
        first_hour, last_hour = DAYPART_HOURS[daypart]
        return f"{first_hour:02d}:00–{last_hour:02d}:00"
    window = state.get(STATE_EXACT_WINDOW_KEY)
    if not isinstance(window, dict):
        return ""
    start, end = window.get("start_total"), window.get("end_total")
    return timeslot_window_label(
        start if isinstance(start, int) else None, end if isinstance(end, int) else None
    )


_SEARCH_UNAVAILABLE: dict[str, str] = {
    "fr": (
        "La recherche d'hôtels est momentanément indisponible — je préfère ne rien "
        "inventer. Pouvez-vous réessayer dans un instant ?"
    ),
    "en": (
        "The hotel search is temporarily unavailable — I'd rather not make anything up. "
        "Could you try again in a moment?"
    ),
    "es": (
        "La búsqueda de hoteles no está disponible en este momento — prefiero no "
        "inventar nada. ¿Puedes intentarlo de nuevo en un momento?"
    ),
    "it": (
        "La ricerca degli hotel è momentaneamente non disponibile — preferisco non "
        "inventare nulla. Puoi riprovare tra un istante?"
    ),
    "de": (
        "Die Hotelsuche ist momentan nicht verfügbar — ich möchte mir nichts ausdenken. "
        "Kannst du es in einem Moment noch einmal versuchen?"
    ),
    "pt": (
        "A pesquisa de hotéis está temporariamente indisponível — prefiro não inventar "
        "nada. Pode tentar novamente daqui a pouco?"
    ),
    "nl": (
        "De hotelzoekfunctie is tijdelijk niet beschikbaar — ik wil liever niets "
        "verzinnen. Kun je het over een moment opnieuw proberen?"
    ),
}


def _search_unavailable_text(language: str) -> str:
    """Deterministic honest line for a turn where the search TOOLS could not
    run (S-CX2, audit F2) — replaces the model's prose, which on this path
    used to claim "no offers in <city>" (false scarcity) when the backend was
    simply unreachable. The orchestrator serves its own degraded template on
    the `search_unavailable` status; this text is the fallback for direct A2A
    consumers and for the synthesis-failure verbatim path."""
    return _SEARCH_UNAVAILABLE.get(language, _SEARCH_UNAVAILABLE["en"])


def stamp_turn_start(callback_context: Any) -> None:
    """`before_agent_callback`: stamps the turn's start time (S-G4 per-phase
    instrumentation — the "total" counter). Runs BEFORE anything else, so it
    covers the whole turn regardless of which path it takes (search / clarify
    / geocode-fail) — `emit_search_datapart` reads it back unconditionally."""
    callback_context.state[_STATE_TURN_T0_KEY] = time.monotonic()
    return None


def _user_checkin_date(
    state: Any, profile_in: dict[str, Any], search_date: Any
) -> str | None:
    """The day the hotel-page links must open on, or None to leave them bare.

    Only a date the USER gave (product rule 2026-09-23: "si le user parle d'une
    date"): a fresh label this turn (`STATE_RESOLVED_DATE_KEY`), or one carried
    from an earlier turn (`profile_in.date` — the profile only ever persists a
    user-stated date). The same-day cutoff swap also writes
    `STATE_RESOLVED_DATE_KEY`, deliberately: the cards on screen are the next
    day's, and a page opening on today would show the closed day instead. A
    silent turn that defaulted to today, or whose carried date was floored to
    today, matches neither and stays bare — the page's own default is today."""
    if not isinstance(search_date, dict):
        return None
    day = search_date.get("date")
    if not isinstance(day, str) or not day:
        return None
    resolved = state.get(STATE_RESOLVED_DATE_KEY)
    if isinstance(resolved, dict) and resolved.get("date") == day:
        return day
    if profile_in.get("date") == day:
        return day
    return None


def _search_context(
    state: Any, raw_delta: dict[str, Any], profile_in: dict[str, Any], search_date: Any
) -> dict[str, Any]:
    """The search this turn actually ran (mcp-dayuse#5): the one source the
    concierge cites in an empty state, instead of what the model remembers.
    Place from this turn's geocode when it ran, else the carried profile;
    budget/window/amenities from the real search_offers args."""
    if raw_delta:
        city, zone = raw_delta.get("last_city"), raw_delta.get("zone")
    else:
        city, zone = profile_in.get("city"), profile_in.get("zone")
    sent = state.get(_STATE_BUDGET_TIMESLOT_KEY) or {}
    daypart = state.get(STATE_DAYPART_KEY)
    day = search_date.get("date") if isinstance(search_date, dict) else None
    search_page = None
    page = state.get(_STATE_SEARCH_PAGE_KEY)
    if isinstance(page, dict):
        cards = state.get(_STATE_RESULTS_KEY) or []
        country = page.get("country_code") or state.get(_STATE_COUNTRY_KEY) or next(
            (c.get("country_code") for c in cards if isinstance(c, dict) and c.get("country_code")), None
        )
        url = build_search_page_url(
            page["path"], country, name=page["name"], checkin_date=day,
            timeslot_start=sent.get("timeslot_start"), timeslot_end=sent.get("timeslot_end"),
        )
        if url:
            search_page = {"name": page["name"], "url": url}
    return {
        "search_page": search_page,
        "city": city or None,
        "zone": zone or None,
        "date": day,
        "daypart": daypart if daypart in DAYPART_HOURS else None,
        "timeslot_start": sent.get("timeslot_start"),
        "timeslot_end": sent.get("timeslot_end"),
        "budget_max": sent.get("budget_max"),
        "amenities": list(state.get(STATE_APPLIED_AMENITIES_KEY) or []),
        "adults": sent.get("adults"),
        "children": sent.get("children"),
        "radius_km": state.get(_STATE_RADIUS_KEY),
    }


def emit_search_datapart(callback_context: Any) -> genai_types.Content | None:
    """`after_agent_callback`: emit ONE event carrying BOTH a short grounded text
    outcome AND the structured `{results, profile_delta}` DataPart from what
    `capture_after_tool` stashed. Both parts must ride in the SAME Content: this
    non-partial event replaces the model's own final text in the A2A artifact
    (last non-partial wins), so the text has to be here too or the orchestrator
    would see a datapart with no `leaf_text` and degrade. Returns None when
    nothing was captured (a clarification-only turn) — the model's own text then
    stands as the response."""
    state = callback_context.state
    # S-G4: the turn's total ms, logged UNCONDITIONALLY (before any early
    # return below) so it covers every path — search, clarify, geocode-fail —
    # not just a successful search. -1 when stamp_turn_start never ran (the
    # unit tests below call this function directly with a bare fake context;
    # same "-1 means the before-callback didn't fire" convention as
    # dayuse_agent_common.metrics._elapsed_ms).
    t0 = state.get(_STATE_TURN_T0_KEY)
    turn_ms = int((time.monotonic() - t0) * 1000) if isinstance(t0, float) else -1
    _metrics_logger.info("dayuse_metric=leaf_turn_total agent=b2c_hotel_search ms=%d", turn_ms)
    results = state.get(_STATE_RESULTS_KEY)
    raw_delta = state.get(_STATE_DELTA_KEY) or {}

    profile_delta: dict[str, Any] = {}
    if raw_delta.get("last_city"):
        profile_delta["city"] = _op_set(raw_delta["last_city"])
    if "last_state_context" in raw_delta:  # may be None → clears the anchor
        profile_delta["state_anchor"] = _op_set(raw_delta["last_state_context"])
    country_code = state.get(_STATE_COUNTRY_KEY)
    if country_code:  # only-when-present — the orchestrator's city-change wipe
        profile_delta["country_anchor"] = _op_set(country_code)  # handles staleness
    # Zone/metro (S-G5, typed ops): the geocode branch's EFFECTIVE zone/metro
    # for THIS turn — previously never persisted at all (audit gap: "zone is
    # lost across turns", zone accepted by geocode_tool/validated by the echo
    # guard but never reaching the profile). Only-when-present: no zone/metro
    # mention this turn is carryover, not a clear (a zone-only change
    # deliberately keeps everything else, S-G1's invalidation rule).
    if "zone" in raw_delta:
        profile_delta["zone"] = _op_set(raw_delta["zone"])
    if "metro" in raw_delta:
        profile_delta["metro"] = _op_set(raw_delta["metro"])
    if state.get("temp:verified_named_hotel"):
        profile_delta["named_hotel"] = _op_set(state["temp:verified_named_hotel"])
    # S-G6: a FRESH date label this turn (datetime_resolver.resolve_search_date)
    # — only-when-present. When the model extracted no date this turn, nothing
    # is stashed here at all (the code-computed search still used the
    # profile's carried-over date/today as its OWN args["date"], but that is
    # never persisted back — carryover already holds it, re-emitting "today"
    # every silent turn would be exactly the audit's "date lost on a later
    # turn" bug in reverse: overwriting a real date with a bootstrap default).
    resolved_date = state.get(STATE_RESOLVED_DATE_KEY)
    if isinstance(resolved_date, dict) and resolved_date.get("date"):
        profile_delta["date"] = _op_set(resolved_date["date"])
        if resolved_date.get("date_reference"):
            profile_delta["date_reference"] = _op_set(resolved_date["date_reference"])
    # Applied amenity filters → the concierge re-learns them. UX1: this is an
    # `_op_set`, i.e. the AUTHORITATIVE state of the filter after this turn,
    # emitted EVEN WHEN EMPTY — which is what makes "enleve le spa" stick. It
    # is lossless because `requested` already CONTAINS the profile's own keys
    # (equipment_ids unions before it subtracts), so the set carries the whole
    # turn's filter, never a fragment.
    #
    # 🪤 The distinction that makes this safe: `None` (the key was never
    # written, because search_offers did not run this turn — a geocode
    # clarification, a find_hotel_by_name) means CARRYOVER and must stay out of
    # the delta; `[]` (written by enforce_equipment_filters, which always
    # writes) means "this turn's search had no filter" and must be sent. The
    # old `state.get(KEY) or []` collapsed the two, so an unconditional emit
    # here would wipe the filters on every clarification turn.
    applied_amenities = state.get(STATE_APPLIED_AMENITIES_KEY)
    if applied_amenities is not None:
        profile_delta["amenities"] = _op_set(list(applied_amenities))
    # Budget / time-slot → the orchestrator's schema keys (exact match, verified
    # 2026-07-21 against apply_profile_delta). The request-source is ALWAYS the
    # non-explicit constant; the concierge's P1 guard upgrades it to "explicit"
    # itself when the message was a bare number/time. Only-when-present: a source
    # is never sent without its value, and an empty capture wipes nothing.
    budget_timeslot = state.get(_STATE_BUDGET_TIMESLOT_KEY) or {}
    if budget_timeslot.get("budget_max") is not None:
        profile_delta["budget_max"] = budget_timeslot["budget_max"]
        profile_delta["budget_request_source"] = _REQUEST_SOURCE_FLEXIBLE
    if budget_timeslot.get("timeslot_start") or budget_timeslot.get("timeslot_end"):
        if budget_timeslot.get("timeslot_start"):
            profile_delta["timeslot_start"] = budget_timeslot["timeslot_start"]
        if budget_timeslot.get("timeslot_end"):
            profile_delta["timeslot_end"] = budget_timeslot["timeslot_end"]
        profile_delta["timeslot_request_source"] = _REQUEST_SOURCE_FLEXIBLE
        # A stated clock window replaces a daypart carried from earlier.
        if read_profile_in(callback_context).get("daypart"):
            profile_delta["daypart"] = {"op": "clear"}
    daypart = state.get(STATE_DAYPART_KEY)
    if daypart in DAYPART_HOURS:
        # ...and a daypart replaces a clock window: one time filter at a time.
        profile_delta["daypart"] = _op_set(daypart)
        for slot in ("timeslot", "timeslot_start", "timeslot_end", "timeslot_mode"):
            profile_delta[slot] = {"op": "clear"}
    # P0-1: party size → the orchestrator's slots. No request-source twin: an
    # occupancy is never inferred or widened, so there is no flexible/explicit
    # distinction to carry. `children` is sent when captured even at 0 ("adults
    # only" is a statement); `adults` is only ever a positive count.
    if budget_timeslot.get("adults") is not None:
        profile_delta["adults"] = budget_timeslot["adults"]
    if budget_timeslot.get("children") is not None:
        profile_delta["children"] = budget_timeslot["children"]

    # Distance origin (A8-a) only when there are cards to attach distances to — a
    # 0-result search carries none. Nested INSIDE profile_delta: the concierge
    # only ever reads `profile_delta` off the wire (agent.py), so a top-level
    # sibling key silently never reaches the profile (S-G9 finding 1).
    distance_origin = state.get(_STATE_DISTANCE_ORIGIN_KEY)
    if distance_origin and results:
        profile_delta["distance_origin"] = distance_origin

    clarify_question = state.get(_STATE_CLARIFY_QUESTION_KEY)
    clarify_turn = results is None and isinstance(clarify_question, str)
    # S-CX2 (audit F2 — false scarcity): the search tools did not produce ANY
    # response this turn, yet the pipeline meant to search: either the breaker
    # short-circuited an MCP call (explicit flag), or the geocode SUCCEEDED
    # (anchor stashed — the instruction then mandates a search) and no search
    # response ever came back (MCP toolset unreachable, call failed, or tool
    # budget spent before the search). Without this, the model's prose stands
    # and reads as a legitimate "no offers in <city>". A clarify turn and a
    # geocode-fail turn (no anchor) keep their honest model text as before.
    search_unavailable = (
        results is None
        and not clarify_turn
        and bool(state.get(_STATE_SEARCH_UNAVAILABLE_KEY) or state.get(_STATE_ANCHOR_KEY))
    )

    payload: dict[str, Any] = {}
    if state.get("temp:resolved_search_location"):
        payload["resolved_location"] = state["temp:resolved_search_location"]
    if results is not None:  # a search ran (even 0 results is a real outcome)
        payload["results"] = results
        if state.get("temp:verified_named_hotel") and results and not any(r.get("price_eur_cents") is not None for r in results):
            payload["identity_only"] = True
        # S-CX6: WHICH day these results (or this dead end) are about, and
        # whether that day is the session's today. The concierge cannot derive
        # it — a carried-over/default date is deliberately never persisted to
        # the profile — and it needs it for two decisions: the mandatory
        # disclosure in the ground-truth block, and date-first recovery chips
        # instead of the budget/zone/filter trio that cannot fix a closed day.
        search_date = state.get(STATE_SEARCH_DATE_KEY)
        if isinstance(search_date, dict) and search_date.get("date"):
            payload["search_date"] = search_date
        # The hotel page opens on today unless told otherwise: a user who asked
        # for another day landed on the wrong day's offers (QA 2026-09-08 n°4).
        payload["search_context"] = _search_context(
            state, raw_delta, read_profile_in(callback_context), search_date
        )
        checkin = _user_checkin_date(state, read_profile_in(callback_context), search_date)
        if checkin:
            payload["results"] = [
                {**r, "url": with_checkin_date(r["url"], checkin)}
                if isinstance(r, dict) and isinstance(r.get("url"), str)
                else r
                for r in results
            ]
    if profile_delta:
        payload["profile_delta"] = profile_delta
    # OBS3: top-level, NOT nested in profile_delta — this is telemetry, not
    # profile state, and `apply_profile_delta` would reject an unknown slot.
    # The concierge folds it into `budget.fired` (see agent.py); an older
    # concierge simply ignores the key, so the two sides can deploy in any order.
    guards_fired = state.get(_STATE_GUARDS_KEY)
    if isinstance(guards_fired, list) and guards_fired:
        payload["guards_fired"] = list(guards_fired)
    if clarify_turn:
        # A geocode homonym clarify ended this turn with no search (S-G10, D3):
        # flag it deterministically so the orchestrator's facade can report
        # `requires_clarification` honestly (it used to be hardcoded False and
        # safe clarifying questions scored as hard failures).
        payload["requires_clarification"] = True
    fallbacks = state.get(_STATE_FALLBACKS_KEY)
    if isinstance(fallbacks, list) and fallbacks:
        payload["fallbacks_fired"] = list(fallbacks)
    named_not_found = state.get(_STATE_NAMED_NOT_FOUND_KEY)
    if isinstance(named_not_found, str):
        payload["named_hotel_not_found"] = named_not_found
    if results is not None and state.get(_STATE_TIMESLOT_FALLBACK_KEY):
        # No offer covers the window: the cards are the closest ones. The
        # concierge makes sure the answer says so (`guard_window_match`).
        payload["timeslot_fallback"] = _state_window_label(state) or True
    if search_unavailable:
        payload["status"] = "search_unavailable"
        if state.get(_STATE_MCP_ERROR_KEY) == "rejected":
            payload["unavailable_reason"] = "rejected"
    if not payload:
        return None

    language = _profile_language(callback_context)
    parts: list[genai_types.Part] = []
    if results is not None:
        timeslot_fallback = bool(state.get(_STATE_TIMESLOT_FALLBACK_KEY))
        parts.append(
            genai_types.Part(
                text=_outcome_text(
                    results, timeslot_fallback, language, state.get(STATE_SEARCH_DATE_KEY),
                    _state_window_label(state),
                )
            )
        )
    elif clarify_turn:
        # This event replaces the model's own final text (last non-partial
        # wins), so the deterministic clarify question must ride here or the
        # question would be lost — the orchestrator's synthesis re-localizes it.
        parts.append(genai_types.Part(text=clarify_question))
    elif search_unavailable:
        # Same replace-the-model's-text mechanics as the clarify path: the
        # deterministic honest line wins over whatever the model improvised.
        parts.append(genai_types.Part(text=_search_unavailable_text(language)))
    parts.append(encode_datapart(payload))
    return genai_types.Content(role="model", parts=parts)


def skip_final_generation(callback_context: Any, llm_request: Any) -> LlmResponse | None:
    """`before_model_callback`: skip the leaf's wasted final-prose LLM call.

    Once search_offers / find_hotel_by_name has run this turn, `capture_after_tool`
    has stashed the normalized results in state. ADK would now call the model one
    more time ONLY to write a prose outcome that `emit_search_datapart` discards
    (last non-partial event wins) — and that the orchestrator never shows the user
    anyway (it re-synthesizes the answer from the structured results + ground-truth
    block). Returning an `LlmResponse` here makes ADK skip that real model call
    (base_llm_flow: a truthy before_model_callback response is yielded, the call is
    not made), cutting the leaf from 3 → 2 internal LLM calls per successful search.

    The canned response carries the SAME code-built outcome text the emit step
    would use, so nothing downstream changes shape.

    Guard on `is None`, NOT falsiness: a 0-result search stashes `[]` (a real
    outcome) and MUST still short-circuit; only the geocode-fail / clarification /
    MCP-degraded paths leave the key unset (capture returns early without stashing),
    and THOSE must still reach the model so it speaks the honest diagnostic that
    becomes the orchestrator's `leaf_text` fallback.

    Must be wired FIRST in `before_model_callback`: the short-circuit returns before
    `after_model_callback` runs, so `llm_timing_after` never fires — placing this
    first means `llm_timing_before` never stamps an orphaned timer for a call that
    won't happen."""
    question = callback_context.state.get(_STATE_CLARIFY_QUESTION_KEY)
    if question and callback_context.state.get(_STATE_RESULTS_KEY) is None:
        return LlmResponse(content=genai_types.Content(role="model", parts=[genai_types.Part(text=question)]))
    if callback_context.state.get(_STATE_SEARCH_UNAVAILABLE_KEY):
        # S-CX2: the breaker already short-circuited an MCP search call this
        # turn — a final prose pass could only echo the failure diagnostic (or
        # worse, improvise a false "no offers"). Skip it with the same
        # deterministic line emit_search_datapart will emit anyway.
        return LlmResponse(
            content=genai_types.Content(
                role="model",
                parts=[
                    genai_types.Part(
                        text=_search_unavailable_text(_profile_language(callback_context))
                    )
                ],
            )
        )
    results = callback_context.state.get(_STATE_RESULTS_KEY)
    if results is None:  # no search this turn → let the model speak (honest diagnostic / clarify)
        return None
    timeslot_fallback = bool(callback_context.state.get(_STATE_TIMESLOT_FALLBACK_KEY))
    return LlmResponse(
        content=genai_types.Content(
            role="model",
            parts=[
                genai_types.Part(
                    text=_outcome_text(
                        results,
                        timeslot_fallback,
                        _profile_language(callback_context),
                        callback_context.state.get(STATE_SEARCH_DATE_KEY),
                        _state_window_label(callback_context.state),
                    )
                )
            ],
        )
    )
