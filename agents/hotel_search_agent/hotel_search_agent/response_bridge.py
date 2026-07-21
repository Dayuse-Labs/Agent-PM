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
profile schema, so the leaf emits in that schema.
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
from google.genai import types as genai_types

# The concierge reports AT MOST 5 (ground-truth cap) — match it so the model
# never ingests more than the caller can use.
_MAX_RESULTS = 5

# Tools whose result is a hotel list/identity worth surfacing as `results`.
_TARGET_TOOLS = {"search_offers", "find_hotel_by_name"}

# temp: → invocation-scoped, discarded after the turn (leaf stays stateless).
_STATE_RESULTS_KEY = "temp:hotel_search_results"
_STATE_DELTA_KEY = "temp:hotel_search_profile_delta"
_STATE_COUNTRY_KEY = "temp:hotel_search_country_code"
# Public (unlike the keys above): written by equipment_ids.enforce_equipment_filters,
# read back here for card stamping + the profile_delta — same cross-callback
# `temp:` hand-off as _STATE_COUNTRY_KEY.
STATE_APPLIED_AMENITIES_KEY = "temp:hotel_search_applied_amenities"


def _iso_alpha2(value: Any) -> str | None:
    """ISO alpha-2 country code or None — never lets a full country name
    ("France") masquerade as a code (the widget's market table is ISO-keyed)."""
    if isinstance(value, str):
        candidate = value.strip()
        if len(candidate) == 2 and candidate.isalpha():
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
    """First decodable DataPart among `parts`, or None — silent no-op, never a
    crash (mirror of the orchestrator's `a2a_datapart.find_datapart`)."""
    for part in parts or []:
        decoded = decode_datapart(part)
        if decoded is not None:
            return decoded
    return None


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


def _first(*values: Any) -> Any:
    """First non-None value — unlike `a or b`, preserves a legit falsy id (0)."""
    for value in values:
        if value is not None:
            return value
    return None


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


def normalize_hotel(hotel: dict[str, Any]) -> dict[str, Any]:
    """One compact hotel card from an MCP_B2C hotel dict (camelCase). Only the
    fields a booking decision / a card needs — never an invented booking link,
    but `mainPhotoNormal` IS resolved to a real photo URL (see `_photo_url`)."""
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
    best = _best_offer(hotel.get("offers") or [])
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


def normalize_search_results(structured: Any) -> list[dict[str, Any]]:
    """Top-5 compact cards from a tool's structuredContent. Handles the
    `search_offers` envelope (`{"results": [...]}`, confirmed live) and the
    `find_hotel_by_name` single-hotel shape (`{"hotel": {...}}`); tolerant of a
    `hotels` key just in case (the server owns the envelope)."""
    if not isinstance(structured, dict):
        return []
    items = structured.get("results")
    if items is None:
        items = structured.get("hotels")
    if items is None:
        single = structured.get("hotel")
        items = [single] if isinstance(single, dict) else []
    return [normalize_hotel(h) for h in (items or [])[:_MAX_RESULTS] if isinstance(h, dict)]


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

    results = normalize_search_results(structured)
    if name == "search_offers":
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


def _outcome_text(results: list[dict[str, Any]]) -> str:
    """A short, code-built (zero-LLM) grounded outcome line. This becomes the
    orchestrator's `leaf_text` — it re-synthesizes the user-facing answer in the
    user's language from this + the structured results' ground-truth block, so
    this text only needs to be a faithful, compact summary (never invented)."""
    if not results:
        return "No day-use offers found for this search."
    names = ", ".join(str(r.get("name")) for r in results if r.get("name"))
    return f"{len(results)} day-use offer(s) found: {names}."


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
    results = state.get(_STATE_RESULTS_KEY)
    raw_delta = state.get(_STATE_DELTA_KEY) or {}

    profile_delta: dict[str, Any] = {}
    if raw_delta.get("last_city"):
        profile_delta["city"] = raw_delta["last_city"]
    if "last_state_context" in raw_delta:  # may be None → clears the anchor
        profile_delta["state_anchor"] = raw_delta["last_state_context"]
    country_code = state.get(_STATE_COUNTRY_KEY)
    if country_code:  # only-when-present — the orchestrator's city-change wipe
        profile_delta["country_anchor"] = country_code  # handles staleness
    # Applied amenity filters → the concierge re-learns them (apply_profile_delta
    # merges without duplicates), so the NEXT turn's profile_in accumulates the
    # filter and search_context_line/active_filters show it SAME turn. Only-when-
    # present: an empty list must never wipe the profile.
    applied_amenities = state.get(STATE_APPLIED_AMENITIES_KEY) or []
    if applied_amenities:
        profile_delta["amenities"] = list(applied_amenities)

    payload: dict[str, Any] = {}
    if results is not None:  # a search ran (even 0 results is a real outcome)
        payload["results"] = results
    if profile_delta:
        payload["profile_delta"] = profile_delta
    if not payload:
        return None

    parts: list[genai_types.Part] = []
    if results is not None:
        parts.append(genai_types.Part(text=_outcome_text(results)))
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
    return LlmResponse(
        content=genai_types.Content(
            role="model", parts=[genai_types.Part(text=_outcome_text(results))]
        )
    )
