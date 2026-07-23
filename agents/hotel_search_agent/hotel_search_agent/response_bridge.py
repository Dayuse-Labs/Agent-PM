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
import time
from typing import Any

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import (
    A2A_DATA_PART_END_TAG,
    A2A_DATA_PART_START_TAG,
    A2A_DATA_PART_TEXT_MIME_TYPE,
)
from google.adk.models.llm_response import LlmResponse
from google.genai import types as genai_types

from hotel_search_agent.inventory import haversine_km

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
# The budget / time-slot the model actually sent search_offers, captured from
# the tool args (search_offers has NATIVE priceRangeMax/timeSlot params — no
# virtual param needed, unlike amenities in S10) and mapped to the profile in
# emit. This is what lets the concierge's S12 guards (budget-vs-duration,
# auto-widen/exhaustion, provenance) finally run on real traffic (S9/S12 gap).
_STATE_BUDGET_TIMESLOT_KEY = "temp:hotel_search_budget_timeslot"
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
# S-G6: set when the exact-window post-filter would have emptied the result
# set entirely — the leaf then falls back to the coarser (hour-rounded)
# results instead of a silent 0, and the outcome text discloses the fallback.
_STATE_TIMESLOT_FALLBACK_KEY = "temp:hotel_search_timeslot_fallback"
# S-G4 per-phase instrumentation: dayuse_agent_common's tool_timing_before/after
# already emit a `dayuse_metric=tool_call tool=geocode_location` / `tool=search_offers`
# row (geocode ms / MCP ms) and llm_timing_before/after a `dayuse_metric=llm_call`
# row (the leaf's own reasoning-pass ms) — this key adds the missing 4th number
# (total turn ms) so a live probe can diff total against the sum of the other
# 3 and see how much is unaccounted for (A2A/ADK overhead, MCP session setup)
# instead of just the phases that happen to call a tool or the model.
_STATE_TURN_T0_KEY = "temp:hotel_search_turn_t0"

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
    .parts` on THIS side accumulates every turn's inbound DataPart across the
    WHOLE A2A session (n_parts grows turn over turn — the leaf's own ADK
    session keeps the full history, unlike the concierge's per-event decode
    loop in `_run_leaf` which naturally lands on the latest by construction).
    Returning the FIRST match — the old behavior — silently pinned every
    profile-driven bridge (amenities, geo context, pagination) to turn 1's
    stale snapshot forever; only `search_cursor` (monotonically advancing,
    never coincidentally equal to turn 1's value) made the bug visible."""
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


def _offer_minutes_of_day(offer: dict[str, Any], hour_key: str, minute_key: str) -> int | None:
    raw_hour: Any = offer.get(hour_key)
    raw_minute: Any = offer.get(minute_key)
    try:
        hour = int(raw_hour)
        minute = int(raw_minute or 0)
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _offer_fits_exact_window(
    offer: dict[str, Any], start_total: int | None, end_total: int | None
) -> bool:
    """S-G6 (A4-c): does `offer` fit ENTIRELY inside the exact requested
    window (minutes-of-day) — same semantics MCP's own timeSlot filter
    documents ("the offer must fit entirely inside the window"), just applied
    at minute precision instead of the whole-hour precision MCP itself can
    filter on. An offer missing a start/end we need to check against never
    passes (never assume a fit we can't verify)."""
    if start_total is not None:
        offer_start = _offer_minutes_of_day(offer, "startHour", "startMinute")
        if offer_start is None or offer_start < start_total:
            return False
    if end_total is not None:
        offer_end = _offer_minutes_of_day(offer, "endHour", "endMinute")
        if offer_end is None or offer_end > end_total:
            return False
    return True


def _first(*values: Any) -> Any:
    """First non-None value — unlike `a or b`, preserves a legit falsy id (0)."""
    for value in values:
        if value is not None:
            return value
    return None


def _positive_budget(value: Any) -> float | None:
    """A search_offers `priceRangeMax` coerced to a positive float, else None.
    The args are model-generated (untrusted): never persist a garbage or a
    non-positive (0 / negative) budget."""
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
    budget_max = _positive_budget(args.get("priceRangeMax"))
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


def _best_offer(offers: list[dict[str, Any]]) -> dict[str, Any] | None:
    priced = [o for o in offers if isinstance(o, dict) and o.get("priceEuro") is not None]
    if priced:
        return min(priced, key=lambda o: o["priceEuro"])
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
    hotel: dict[str, Any], exact_window: tuple[int | None, int | None] | None = None
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
        "amenities": _flatten_amenities(hotel.get("amenities")),
    }
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
    # doesn't send one today (probed live 2026-07-20: countryName + slug only) —
    # keep the preference so a server-provided code wins the day it appears.
    country_code = _iso_alpha2(hotel.get("countryCode"))
    if country_code:
        card["country_code"] = country_code
    # S-G7: the hotel's own local currency (display-only, see `_iso_currency`) —
    # `search_offers` sends this directly per hotel (probed live 2026-07-23),
    # unlike country_code above which it never sends.
    currency_code = _iso_currency(hotel.get("currencyCode"))
    if currency_code:
        card["currency_code"] = currency_code
    offers = hotel.get("offers") or []
    if exact_window is not None:
        start_total, end_total = exact_window
        offers = [
            o for o in offers if isinstance(o, dict) and _offer_fits_exact_window(o, start_total, end_total)
        ]
    best = _best_offer(offers)
    if best:
        price = _format_price_eur_cents(best.get("priceEuro"))
        if price:
            card["price"] = price
        start, end = _hhmm(best.get("startHour"), best.get("startMinute")), _hhmm(
            best.get("endHour"), best.get("endMinute")
        )
        if start and end:
            card["timeslots"] = [{"start": start, "end": end}]
    return card


def normalize_search_results(
    structured: Any,
    exclude_ids: set[Any] | None = None,
    exact_window: tuple[int | None, int | None] | None = None,
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
    of its offers fit inside the true requested minutes (see
    `_offer_fits_exact_window`) — a hotel whose only offer is 07:00-13:00 is
    not a real match for "07:30-13:30" even though MCP's own hour-rounded
    filter (07:00-14:00) returned it. `find_hotel_by_name` never passes
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
            start_total, end_total = exact_window
            fits_any = any(
                isinstance(o, dict) and _offer_fits_exact_window(o, start_total, end_total)
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


# --- callbacks ------------------------------------------------------------------------------
def inject_pagination_offset(tool: Any, args: dict[str, Any], tool_context: Any) -> None:
    """`before_tool_callback` (S-G5, A7): the ONLY writer of search_offers'
    `from` — the model is never taught pagination (there is nothing in the
    message to extract; whether this is page 2 lives entirely in
    `profile_in.search_cursor`, S-G1's `advance_search_cursor`). Live-probed
    2026-07-23 against MCP_B2C staging: `search_offers` accepts `from`
    (offset, default 0) / `size` (page size, default 10, max 50) and an
    offset advanced by a full page returns genuinely disjoint hotel ids —
    real server-side pagination, no `excludeHotelIds`-style param exists
    (confirmed: an unrecognized key is a hard schema-validation error). So the
    `from` offset is the PRIMARY pagination driver; `shown_hotel_ids`
    (normalize_search_results, above) stays a client-side safety net for
    misaligned page boundaries. Any `from` the model itself supplied is
    unconditionally overwritten — same doctrine as `hotelEquipmentIds`: the
    LLM never owns a filter/paging value."""
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
        if isinstance(tool_response, dict) and tool_response.get("ok"):
            delta = tool_response.get("profile_delta")
            if isinstance(delta, dict) and delta:
                tool_context.state[_STATE_DELTA_KEY] = delta
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
        return None

    if name not in _TARGET_TOOLS or not isinstance(tool_response, dict):
        return None
    if tool_response.get("isError") or tool_response.get("ok") is False:
        return None  # a real failure — leave it untouched for the model to relay

    structured = tool_response.get("structuredContent")
    if not isinstance(structured, dict):
        structured = _parse_content_text(tool_response)
    if not isinstance(structured, dict):
        return None

    exclude_ids: set[Any] | None = None
    strict_window: tuple[int | None, int | None] | None = None
    if name == "search_offers":
        # S-G5 pagination safety net: hotels already shown across earlier turns
        # (accumulated at the profile, S-G1) are filtered out before the top-5
        # cut. A named lookup (find_hotel_by_name) never excludes — see below.
        shown = read_profile_in(tool_context).get("shown_hotel_ids")
        if isinstance(shown, list) and shown:
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
            if isinstance(start_total, int) and isinstance(end_total, int):
                strict_window = (start_total, end_total)
    results = normalize_search_results(structured, exclude_ids, strict_window)
    timeslot_fallback = False
    if strict_window is not None and not results:
        # The exact-minute filter emptied the set: fall back to the coarser
        # hour-rounded results (never a silent 0) — the outcome text discloses it.
        fallback_results = normalize_search_results(structured, exclude_ids, None)
        if fallback_results:
            results = fallback_results
            timeslot_fallback = True
    if timeslot_fallback:
        tool_context.state[_STATE_TIMESLOT_FALLBACK_KEY] = True
    if name == "search_offers":
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


def _op_set(value: Any) -> dict[str, Any]:
    """S-G1 typed-ops envelope for an explicit "set" — the concierge's
    `apply_profile_delta` reducer accepts this identically to a bare value
    (S-G1 retro-compat), so this is purely the leaf's migration to the
    auditable shape (S-G5) for the geo slots it owns; amenities/budget/
    timeslot stay flat here on purpose (out of this phase's scope)."""
    return {"op": "set", "value": value}


def _outcome_text(results: list[dict[str, Any]], timeslot_fallback: bool = False) -> str:
    """A short, code-built (zero-LLM) grounded outcome line. This becomes the
    orchestrator's `leaf_text` — it re-synthesizes the user-facing answer in the
    user's language from this + the structured results' ground-truth block, so
    this text only needs to be a faithful, compact summary (never invented).

    S-G6 (A4-c): `timeslot_fallback` — set when the exact-minute window would
    have emptied the results entirely and the leaf fell back to the coarser
    hour-rounded set instead of a silent 0 — appends an honest disclosure so
    the synthesis never implies these hotels cover the exact time asked."""
    if not results:
        return "No day-use offers found for this search."
    names = ", ".join(str(r.get("name")) for r in results if r.get("name"))
    text = f"{len(results)} day-use offer(s) found: {names}."
    if timeslot_fallback:
        text += (
            " No offer covers the exact requested time window; showing the "
            "closest matches instead."
        )
    return text


def stamp_turn_start(callback_context: Any) -> None:
    """`before_agent_callback`: stamps the turn's start time (S-G4 per-phase
    instrumentation — the "total" counter). Runs BEFORE anything else, so it
    covers the whole turn regardless of which path it takes (search / clarify
    / geocode-fail) — `emit_search_datapart` reads it back unconditionally."""
    callback_context.state[_STATE_TURN_T0_KEY] = time.monotonic()
    return None


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
    if raw_delta.get("zone"):
        profile_delta["zone"] = _op_set(raw_delta["zone"])
    if raw_delta.get("metro"):
        profile_delta["metro"] = _op_set(raw_delta["metro"])
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
    # Applied amenity filters → the concierge re-learns them (apply_profile_delta
    # merges without duplicates), so the NEXT turn's profile_in accumulates the
    # filter and search_context_line/active_filters show it SAME turn. Only-when-
    # present: an empty list must never wipe the profile.
    applied_amenities = state.get(STATE_APPLIED_AMENITIES_KEY) or []
    if applied_amenities:
        profile_delta["amenities"] = list(applied_amenities)
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

    # Distance origin (A8-a) only when there are cards to attach distances to — a
    # 0-result search carries none. Nested INSIDE profile_delta: the concierge
    # only ever reads `profile_delta` off the wire (agent.py), so a top-level
    # sibling key silently never reaches the profile (S-G9 finding 1).
    distance_origin = state.get(_STATE_DISTANCE_ORIGIN_KEY)
    if distance_origin and results:
        profile_delta["distance_origin"] = distance_origin

    payload: dict[str, Any] = {}
    if results is not None:  # a search ran (even 0 results is a real outcome)
        payload["results"] = results
    if profile_delta:
        payload["profile_delta"] = profile_delta
    if not payload:
        return None

    parts: list[genai_types.Part] = []
    if results is not None:
        timeslot_fallback = bool(state.get(_STATE_TIMESLOT_FALLBACK_KEY))
        parts.append(genai_types.Part(text=_outcome_text(results, timeslot_fallback)))
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
    results = callback_context.state.get(_STATE_RESULTS_KEY)
    if results is None:  # no search this turn → let the model speak (honest diagnostic / clarify)
        return None
    timeslot_fallback = bool(callback_context.state.get(_STATE_TIMESLOT_FALLBACK_KEY))
    return LlmResponse(
        content=genai_types.Content(
            role="model", parts=[genai_types.Part(text=_outcome_text(results, timeslot_fallback))]
        )
    )
