"""Inline MCP tools of the orchestrator (S07): real MCP_B2C wiring for
`get_hotel_details`, `compare_hotels`, `generate_booking_link` — the 3 tools
the concierge calls itself (never through an A2A leaf), least-privilege:
these are the ONLY 3 of the 6 MCP_B2C tools this module ever calls (search
and FAQ belong to the two leaves).

Named-hotel lookup guard (item 4) — `get_hotel_details`/`generate_booking_link`:
every hotel reference resolves against the session's on-screen shortlist
FIRST (`profile.last_results`, fuzzy match — profile.py's
`resolve_hotel_reference`), MCP `find_hotel_by_name` only as the fallback for
a hotel mentioned by name that isn't currently on screen. A hotel the
concierge just recommended must never dead-end (prod session 34d216e3,
agent-usa). `compare_hotels` stays shortlist-only (phase scope, item 1) and
never falls back to `find_hotel_by_name` — comparing a hotel the session
hasn't shown yet is out of scope.

R9 / guard #12 (`generate_booking_link`): the MCP tool itself is STATELESS —
probed live against MCP_B2C staging, it happily returns a real tracked link
for a first-ever call with `confirmed=true` (it has no memory of a prior
confirmed=false round-trip). The entire confirmation guarantee therefore
lives HERE, in code: the `confirmed` flag actually sent to MCP is derived
ONLY from `profile.pending_booking` (server-side, persisted turn state) —
never from whatever the caller asserts. See `generate_booking_link` below.

Connection: one MCP session per call (streamable HTTP handshake), NOT a
persistent cross-turn session like the leaves' McpToolset — simpler, correct,
and this phase's scope is the 3 tools' wiring + the guards, not an inline-tool
latency parade. `CONCIERGE_INLINE_MCP_TIMEOUT_SECONDS` (default 5 s) is the
single owner of the whole operation's budget (connect + calls), no retry —
same "honest degradation" posture as `_run_leaf`.
"""
from __future__ import annotations

import asyncio
import math
import os
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, AsyncIterator

import httpx
from b2c_common import (
    build_hotel_page_url,
    display_price_euro,
    display_price_hotel,
    format_minor_amount,
    hotel_currency_price,
    with_checkin_date,
)
from b2c_common.observability import mark_level, observation, trace_context_carrier
from b2c_common.offer_facts import selected_offer_facts
from b2c_common.party_discovery import possible_party
from b2c_common.pricing import has_unverified_zero_price, offer_totals
from b2c_common.room_requirements import bedding_matches
from b2c_common.timeslot import parse_hhmm, slot_covers_window
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .display_currency import HOTEL, shows_hotel_currency
from .profile import (
    SessionProfile,
    resolve_hotel_name_on_screen,
    resolve_hotel_reference,
    resolve_hotel_reference_strict,
    resolve_hotel_references,
    resolve_shortlist_ordinal,
)

_INLINE_MCP_TIMEOUT = float(os.environ.get("CONCIERGE_INLINE_MCP_TIMEOUT_SECONDS", "5.0"))


def _connection_params() -> tuple[str, dict[str, str]]:
    token = os.environ.get("MCP_B2C_AUTH_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = os.environ.get("MCP_B2C_URL", "http://localhost:8099/mcp")
    return url, headers


@asynccontextmanager
async def _mcp_session() -> AsyncIterator[ClientSession]:
    url, headers = _connection_params()
    async with httpx.AsyncClient(headers=headers, timeout=_INLINE_MCP_TIMEOUT) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


async def _call_tool(session: ClientSession, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Calls one MCP_B2C tool; NEVER raises — a transport error, a tool-level
    error (`isError`), or an unparsable payload all become an honest
    `{"ok": False, "error": ...}` (same posture as `_run_leaf`'s degradation),
    never an invented result.

    OBS2: typed `tool` (unlike the leaves' MCP calls, this one runs entirely
    OUTSIDE ADK's own tool-calling machinery — a plain client-session call
    the concierge makes itself — so nothing else ever types it).

    OBS4: `meta` = the W3C trace context in the MCP `_meta` field, so MCP_B2C
    can put its ES queries in this turn's trace (OBS10 owns the server side;
    the wire format is OBS4-TRACE-PROPAGATION-CONTRACT.md §3). Being outside
    ADK is exactly why it has to be passed here: ADK's own McpToolset already
    injects the same carrier for the leaves' MCP calls. `_meta` is a
    spec-sanctioned passthrough — a server that ignores it is unaffected."""
    with observation(as_type="tool", name=f"mcp-{name}"):
        try:
            result = await session.call_tool(name, arguments, meta=trace_context_carrier() or None)
        except Exception as exc:  # noqa: BLE001 — an MCP failure degrades, never crashes
            mark_level("ERROR", status_message="inline_mcp_call_failed")
            return {"ok": False, "error": f"{name} failed: {type(exc).__name__}"}
        if result.isError:
            message = (
                "".join(getattr(c, "text", "") for c in (result.content or [])) or f"{name}: tool error"
            )
            mark_level("ERROR", status_message="inline_mcp_call_failed")
            return {"ok": False, "error": message}
        if result.structuredContent is not None:
            return {"ok": True, "data": result.structuredContent}
        mark_level("ERROR", status_message="inline_mcp_call_failed")
        return {"ok": False, "error": f"{name}: no structured response"}


async def _resolve_hotel_id(
    session: ClientSession,
    reference: str,
    profile: SessionProfile,
    llm_hotel_name: str | None = None,
) -> tuple[int | None, str | None]:
    with observation(as_type="guardrail", name="resolve-named-hotel"):
        return await _resolve_hotel_id_impl(session, reference, profile, llm_hotel_name)


async def _resolve_hotel_id_impl(
    session: ClientSession,
    reference: str,
    profile: SessionProfile,
    llm_hotel_name: str | None = None,
) -> tuple[int | None, str | None]:
    """Named-hotel lookup guard (item 4, hardened S12 audit 2026-07-20): a
    STRONG shortlist hit (exact/substring name match) resolves immediately,
    zero MCP round-trip. A hotel that only matches the shortlist via the WEAK
    distinctive-token fallback — or doesn't match at all — is never trusted
    alone: it always reaches the global `find_hotel_by_name` first (an
    explicitly named hotel absent from a stale shortlist must never be
    masked by a same-word coincidence with an unrelated on-screen entry). The
    weak shortlist hit is used only as a last-resort fallback if MCP itself
    degrades or finds nothing. Returns `(hotel_id, resolved_name)`,
    `(None, None)` when nothing resolves."""
    # A bare list position ("2", "the first") the user typed to pick from the
    # numbered shortlist just shown resolves from that shortlist directly —
    # never MCP (the shortlist already holds the id; find_hotel_by_name's
    # exact-city filter mis-handles greater-metro inventory). Checked FIRST so
    # a digit is never fed to name matching (which would fuzzy-hit a wrong or
    # no hotel).
    ordinal_hit = resolve_shortlist_ordinal(reference, profile.last_results)
    if ordinal_hit is not None and ordinal_hit.get("hotel_id") is not None:
        return int(ordinal_hit["hotel_id"]), str(ordinal_hit["name"])

    strong_hit = resolve_hotel_reference_strict(reference, profile.last_results)
    if strong_hit is not None and strong_hit.get("hotel_id") is not None:
        return int(strong_hit["hotel_id"]), str(strong_hit["name"])

    # The name MCP is asked for is the one the triage read (`hotel_name`), on
    # every route: it strips request phrasing in any language. QA14707 (Q05
    # trace C2, Q11): never the raw message — « Je confirme » once became
    # find_hotel_by_name's `name`. With no name from the triage, nothing is
    # asked of MCP, and only the on-screen shortlist can still resolve below.
    result: dict[str, Any] = {"ok": False}
    if llm_hotel_name:
        args: dict[str, Any] = {"name": llm_hotel_name}
        if profile.city:
            args["cityName"] = profile.city
        result = await _call_tool(session, "find_hotel_by_name", args)
    if result["ok"]:
        # find_hotel_by_name wraps the resolved identity under "hotel"
        # (verified live) — NOT flat at the top level, unlike
        # get_hotel_details's own top-level fields when accessed directly.
        hotel = result["data"].get("hotel") or result["data"]
        hotel_id = hotel.get("hotelId") or hotel.get("id")
        if hotel_id is not None:
            return int(hotel_id), hotel.get("name")

    # The name the triage read, against the names on screen, spaces and case
    # aside (« Double Tree » / « DoubleTree by Hilton … », prod 2026-10-27):
    # MCP knows no hotel by that spelling, the card the user means is there.
    on_screen = resolve_hotel_name_on_screen(llm_hotel_name, profile.last_results)
    if on_screen is not None and on_screen.get("hotel_id") is not None:
        return int(on_screen["hotel_id"]), str(on_screen["name"])

    weak_hit = resolve_hotel_reference(reference, profile.last_results)
    if weak_hit is not None and weak_hit.get("hotel_id") is not None:
        return int(weak_hit["hotel_id"]), str(weak_hit["name"])
    return None, None


# --- Display normalization ---------------------------------------------------------------------


def _flatten_amenities(raw_amenities: Any) -> list[str]:
    """MCP amenities are `[{"id": int, "name": str}, ...]` — flattened to
    plain name strings so ground_truth.py / amenity_guard.py (both built for
    the search leaf's own `list[str]` shape) work the same regardless of
    source."""
    names: list[str] = []
    for item in raw_amenities or []:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
        elif isinstance(item, str):
            names.append(item)
    return names


def _hhmm(hour: Any, minute: Any) -> str | None:
    """S-G6: "HH:MM" from an offer's hour/minute pair, or None — mirrors
    hotel_search_agent.response_bridge._hhmm (no cross-package import, B3:
    each side owns its own tiny formatting helper)."""
    if hour is None:
        return None
    try:
        return f"{int(hour):02d}:{int(minute or 0):02d}"
    except (TypeError, ValueError):
        return None


def _format_price_eur_cents(cents: Any) -> str | None:
    """P3 (AUDIT-REWORK-2026-07.md): `priceEuro` is EUR cents. S-G7: the
    profile DOES now carry a user-currency signal (`profile.currency`,
    S-G1/S-G2 native-context) and MCP_B2C exposes a per-hotel `currencyCode`
    (live-probed 2026-07-23) — but neither is a numeric price in that
    currency, and MCP performs no conversion server-side (verified: a hotel's
    `priceEuro` is identical whether its own `currencyCode` is EUR or USD/GBP).
    Display therefore stays EUR here — the simple, honest default — while
    `agent.py::_synthesize_with_guards` discloses the mismatch to the user
    instead of silently implying this is their own currency."""
    if cents is None:
        return None
    try:
        return f"€{float(cents) / 100:.2f}"
    except (TypeError, ValueError):
        return None


def _price_eur_cents(cents: Any) -> int | None:
    """S-CX3a: the same `priceEuro`, kept NUMERIC on the card — mirrors
    hotel_search_agent.response_bridge._price_eur_cents (no cross-package
    import, B3: each side owns its own tiny formatting helper). Until now the
    `€X.XX` display string was the only survivor of normalization, so nothing
    downstream could compare a price to the client's budget."""
    if cents is None:
        return None
    try:
        return round(float(cents))
    except (TypeError, ValueError):
        return None


def _iso_currency(value: Any) -> str | None:
    """ISO 4217 alpha-3 currency code or None — mirrors
    hotel_search_agent.response_bridge._iso_currency (no cross-package
    import, B3: each side owns its own tiny formatting helper)."""
    if isinstance(value, str):
        candidate = value.strip()
        if len(candidate) == 3 and candidate.isalpha():
            return candidate.upper()
    return None


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


def _normalize_hotel_for_display(hotel: dict[str, Any], best_offer: dict[str, Any] | None) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "id": hotel.get("hotelId") or hotel.get("id"),
        "name": hotel.get("name"),
        "city": hotel.get("cityName") or hotel.get("city"),
        "country": hotel.get("countryName") or hotel.get("country"),
        "rating": hotel.get("globalAverageRating"),
        # S-CX3a: `totalReview` rides the shared MCP identity block, so the
        # details/compare path carries the review count too (see the leaf's
        # normalize_hotel) — a card must not describe quality the same way
        # whether the average rests on 2 reviews or 400.
        "rating_count": hotel.get("totalReview"),
        "stars": hotel.get("starRating"),
        "amenities": _flatten_amenities(hotel.get("amenities")),
    }
    photo = _photo_url(hotel.get("mainPhotoNormal"))
    if photo:
        normalized["image_urls"] = [photo]
    currency_code = _iso_currency(hotel.get("currencyCode"))
    if currency_code:
        normalized["currency_code"] = currency_code
    # S-G12: hotel-page link from the server's own ES `slug` + market table
    # (b2c_common, same builder as the search leaf's cards). Defensive: the
    # get_hotel_details payload shape was not re-probed for `slug` — absent
    # fields simply mean no link on the card, never a name-slugified guess.
    url = build_hotel_page_url(
        hotel.get("slug"), hotel.get("countryCode"), hotel.get("countryName") or hotel.get("country")
    )
    if url:
        normalized["url"] = url
    if best_offer:
        # Same selected-offer evidence as the search leaf's card.
        facts = selected_offer_facts(hotel, best_offer)
        if facts:
            normalized["offer_facts"] = facts
        totals = offer_totals(best_offer)
        if totals:
            normalized["offer_totals"] = totals
        start = _hhmm(best_offer.get("startHour"), best_offer.get("startMinute"))
        end = _hhmm(best_offer.get("endHour"), best_offer.get("endMinute"))
        if start and end:
            normalized["timeslots"] = [{"start": start, "end": end}]
        shown_price = display_price_euro(best_offer, hotel)
        normalized["price"] = _format_price_eur_cents(shown_price)
        normalized["price_eur_cents"] = _price_eur_cents(shown_price)
        hotel_fields = hotel_currency_price(best_offer, hotel)
        hotel_fields.pop("hotel_original_price", None)
        normalized.update(hotel_fields)
        # S-CX5: the offer's identity travels with its price (same rule and
        # same keys as the search leaf's `normalize_hotel`) so the booking step
        # can reuse THIS offer rather than re-deriving one.
        offer_id = best_offer.get("ratePlanUuid")
        if isinstance(offer_id, str) and offer_id.strip():
            normalized["offer_id"] = offer_id.strip()
        offer_date = best_offer.get("availabilityDate")
        if isinstance(offer_date, str) and offer_date.strip():
            normalized["offer_date"] = offer_date.strip()
    return normalized


# --- Public inline tools ------------------------------------------------------------------------


async def get_hotel_details(
    hotel_reference: str,
    profile: SessionProfile,
    picked_hotel_id: int | None = None,
    llm_hotel_name: str | None = None,
    preserve_shown_offer: bool = False,
) -> dict[str, Any]:
    """Real MCP_B2C `get_hotel_details`, hotel resolved via the named-hotel
    lookup guard — or taken straight from `picked_hotel_id` when the spine
    already resolved WHICH hotel (S-CX5: "montre-moi le moins cher" points at
    one of the cards on screen, and no amount of name matching would find a
    hotel from those words). Returns `{"ok": True, "hotel": {...normalized...}}`
    or `{"ok": False, "error": ...}` — never raises, never invents."""
    if picked_hotel_id is None and not (hotel_reference or "").strip():
        return {"ok": False, "error": "no hotel reference in the message"}
    try:
        async with asyncio.timeout(_INLINE_MCP_TIMEOUT):
            async with _mcp_session() as session:
                hotel_id: int | None = picked_hotel_id
                guards_fired: list[str] = []
                if hotel_id is None:
                    hotel_id, _ = await _resolve_hotel_id(
                        session, hotel_reference, profile, llm_hotel_name
                    )
                    guards_fired.append("named_hotel_lookup")
                if hotel_id is None:
                    return {"ok": False, "error": "hotel not found", "guards_fired": guards_fired}
                # Dated lookup: the session's day, else the day of the offer on
                # screen. Undated, MCP returns every upcoming offer and the
                # first one can belong to another day or formula.
                args: dict[str, Any] = {"hotelId": hotel_id}
                shown = _shortlist_offer(hotel_id, profile)
                requested_date = profile.date or (shown.get("offer_date") if shown else None)
                if requested_date:
                    args["date"] = requested_date
                result = await _call_tool(session, "get_hotel_details", args)
                if not result["ok"]:
                    return {**result, "guards_fired": guards_fired}
                data = result["data"]
                hotel = data.get("hotel") or {}
                if preserve_shown_offer and hotel.get("hotelId", hotel.get("id")) != hotel_id:
                    return {"ok": False, "error": "details returned a different hotel identity"}
                offers = data.get("offers") or []
                available_offers = []
                if requested_date:
                    day_profile = replace(profile, date=requested_date)
                    for offer in offers:
                        if _search_offer([offer], hotel, day_profile) is None:
                            continue
                        normalized_offer = _normalize_hotel_for_display(hotel, offer)
                        available_offers.append({k: normalized_offer[k] for k in
                            ("offer_id", "offer_date", "timeslots", "price", "offer_totals",
                             "hotel_price", "hotel_price_minor", "hotel_currency_code")
                            if k in normalized_offer})
                if profile.date:
                    offers = [o for o in offers if o.get("availabilityDate") == profile.date]
                if shown is not None:
                    # A details question keeps the formula already displayed.
                    # If it disappeared, report hotel facts without another price.
                    offers = [o for o in offers if
                              o.get("ratePlanUuid") == shown.get("offer_id")
                              and o.get("availabilityDate") == shown.get("offer_date")]
                if preserve_shown_offer:
                    offers = [o for o in offers if shown
                              and _hhmm(o.get("startHour"), o.get("startMinute")) == shown.get("start_time")
                              and _hhmm(o.get("endHour"), o.get("endMinute")) == shown.get("end_time")]
                    # Identity, day, slot, cutoff and price only: a card shown
                    # as "closest" to the hours never covered them, and the
                    # search filters already passed when it was displayed.
                    best = _search_offer(offers, hotel, replace(
                        profile, date=requested_date, timeslot_start=None, timeslot_end=None,
                        budget_max=None, adults=None, children=None,
                        room_requirements=None, pending_party_total=None,
                    ))
                elif shown is None and requested_date:
                    # An older hotel can have left the visible shortlist. Its
                    # first/cheapest formula is not evidence for the requested
                    # hours. Details may quote a higher price, so the budget
                    # stays a search filter, separate from this slot choice.
                    best = _search_offer(offers, hotel, replace(
                        profile, date=requested_date, budget_max=None,
                        adults=None, children=None,
                    ))
                else:
                    best = offers[0] if offers else None
                normalized = _normalize_hotel_for_display(hotel, best)
                if shown is None and requested_date and best is None:
                    normalized["requested_offer_unavailable"] = True
                if available_offers:
                    normalized["available_offers"] = available_offers[:20]
                    normalized["available_offers_truncated"] = len(available_offers) > 20
                if preserve_shown_offer and best is None:
                    normalized["shown_offer_unavailable"] = True
                # Same rule as the search leaf's cards: `profile.date` only ever
                # holds a user-given date (or the same-day cutoff swap), so the
                # hotel page opens on the day the user asked for, not today.
                if isinstance(normalized.get("url"), str) and profile.date:
                    normalized["url"] = with_checkin_date(normalized["url"], profile.date)
                return {"ok": True, "hotel": normalized, "guards_fired": guards_fired}
    except Exception as exc:  # noqa: BLE001 — degrade honestly, never crash the turn
        return {"ok": False, "error": f"get_hotel_details failed: {type(exc).__name__}"}


def _search_offer(offers: list[Any], hotel: dict[str, Any], profile: SessionProfile) -> dict[str, Any] | None:
    """The cheapest offer bookable on `profile.date` that fits the session's
    budget (fee-inclusive EUR total) and hours (the site's shared rule,
    `slot_covers_window`) — never an expired, unpriced, undated or unidentified
    one. Property amenities and policy eligibility are separate evidence, not
    implied by the existence of this offer."""
    start, end = parse_hhmm(profile.timeslot_start), parse_hhmm(profile.timeslot_end)
    candidates = []
    for offer in offers:
        if not isinstance(offer, dict) or not profile.date or offer.get("availabilityDate") != profile.date:
            continue
        if not isinstance(offer.get("ratePlanUuid"), str) or not offer["ratePlanUuid"].strip():
            continue
        if parse_hhmm(_hhmm(offer.get("startHour"), offer.get("startMinute"))) is None or parse_hhmm(_hhmm(
            offer.get("endHour"), offer.get("endMinute")
        )) is None:
            continue
        deadline = offer.get("cutoffDeadlineUtc")
        if deadline is not None:
            try:
                cutoff = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                if cutoff.tzinfo is None or cutoff <= datetime.now(UTC):
                    continue
            except (AttributeError, TypeError, ValueError):
                continue
        price = display_price_euro(offer, hotel)
        if (isinstance(price, bool) or not isinstance(price, (int, float))
                or not math.isfinite(price) or price <= 0):
            continue
        if profile.budget_max is not None:
            total = offer_totals(offer).get("EUR")
            if total is None or total > profile.budget_max * 100:
                continue
        if (start is not None or end is not None) and not slot_covers_window(
            offer.get("startHour"), offer.get("endHour"), start, end
        ):
            continue
        # PORT1 slice 5: the bed asked for, and a capacity for the party —
        # a possible one while its composition is unknown, else a proven one
        # (missing capacity cannot prove a stated party fits).
        if not bedding_matches(offer, profile.room_requirements):
            continue
        if profile.pending_party_total is not None:
            if not possible_party(offer, profile.pending_party_total):
                continue
        elif any(
            needed is not None and needed > 0 and (
                isinstance(offer.get(field), bool) or not isinstance(offer.get(field), int)
                or offer[field] < needed
            )
            for field, needed in (("capacity", profile.adults), ("childrenCapacity", profile.children))
        ):
            continue
        candidates.append(offer)
    return min(candidates, key=lambda offer: display_price_euro(offer, hotel)) if candidates else None


async def compare_hotels(message: str, profile: SessionProfile) -> dict[str, Any]:
    """Real MCP_B2C `compare_hotels` — works OFF THE SHORTLIST only (phase
    scope, item 1: "travaillent sur la shortlist du tour"), never MCP
    `find_hotel_by_name` — comparing a hotel the session hasn't shown yet is
    out of scope (unlike the single-hotel lookup guard, item 4, which
    `get_hotel_details`/`generate_booking_link` do need). Two or more hotels
    named in `message` resolve against `profile.last_results`
    (`resolve_hotel_references`, fuzzy); when fewer than 2 are named, compares
    the on-screen shortlist itself by default — "compare these hotels" needs
    no explicit naming right after a search."""
    hotel_ids: list[int] = []
    seen: set[int] = set()
    for hotel in resolve_hotel_references(message, profile.last_results):
        candidate = hotel.get("hotel_id")
        if candidate is not None and int(candidate) not in seen:
            seen.add(int(candidate))
            hotel_ids.append(int(candidate))
    if len(hotel_ids) < 2:
        for hotel in profile.last_results or []:
            candidate = hotel.get("hotel_id")
            if candidate is not None and int(candidate) not in seen:
                seen.add(int(candidate))
                hotel_ids.append(int(candidate))
    if len(hotel_ids) < 2:
        return {"ok": False, "error": "need at least 2 hotels to compare"}
    try:
        async with asyncio.timeout(_INLINE_MCP_TIMEOUT):
            if profile.date or any(_shortlist_offer(i, profile) for i in hotel_ids):
                # MCP `compare_hotels` returns ONE `bestOffer` per hotel: even
                # with its optional `date` it can be another formula than the
                # card's, and without it another day. Revalidate ONLY the
                # displayed offers through the dated details tool; never
                # replace them. At most five read-only calls, concurrent under
                # this one timeout.
                details = await asyncio.gather(*(
                    get_hotel_details("", profile, picked_hotel_id=i, preserve_shown_offer=True)
                    for i in hotel_ids[:5]
                ))
                if not all(r.get("ok") for r in details):
                    return {"ok": False, "error": "comparison details unavailable"}
                return {"ok": True, "hotels": [r["hotel"] for r in details], "best_by": {}}
            async with _mcp_session() as session:
                result = await _call_tool(session, "compare_hotels", {"hotelIds": hotel_ids[:10]})
                if not result["ok"]:
                    return result
                data = result["data"]
                hotels = [
                    _normalize_hotel_for_display(entry, entry.get("bestOffer"))
                    for entry in data.get("hotels") or []
                ]
                return {"ok": True, "hotels": hotels, "best_by": data.get("bestBy") or {}}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"compare_hotels failed: {type(exc).__name__}"}


async def _confirm_pending_offer(pending: dict[str, Any]) -> dict[str, Any]:
    """The confirmed=true branch of R9/guard #12: reuses the EXACT offer
    identity stored at the quote step (never re-derives it from the
    confirmation message — a bare "yes" carries no hotel name to resolve)."""
    try:
        async with asyncio.timeout(_INLINE_MCP_TIMEOUT):
            async with _mcp_session() as session:
                args: dict[str, Any] = {
                    "hotelId": pending["hotel_id"],
                    "date": pending["date"],
                    "confirmed": True,
                }
                if pending.get("rate_plan_uuid"):
                    args["ratePlanUuid"] = pending["rate_plan_uuid"]
                else:
                    args["ratePlanId"] = pending["rate_plan_id"]
                result = await _call_tool(session, "generate_booking_link", args)
                if not result["ok"]:
                    return result
                link = result["data"].get("link") or {}
                # S-CX5: the offer's own facts ride along so the caller can
                # build a card that STATES what the link books (date, slot,
                # price) instead of pasting a bare URL.
                return {
                    "ok": True,
                    "confirmed": True,
                    "url": link.get("url"),
                    "hotel_id": pending.get("hotel_id"),
                    "hotel_name": pending.get("hotel_name"),
                    "date": pending.get("date"),
                    "start_time": pending.get("start_time"),
                    "end_time": pending.get("end_time"),
                    "price": pending.get("price"),
                    "image_url": pending.get("image_url"),
                    "hotel_url": pending.get("hotel_url"),
                    "city": pending.get("city"),
                    "rating": pending.get("rating"),
                    "rating_count": pending.get("rating_count"),
                    "stars": pending.get("stars"),
                }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"generate_booking_link failed: {type(exc).__name__}"}


def _best_offer(
    offers: list[Any], date: str | None = None, hotel: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """The cheapest priced offer ON ONE DAY — the session's `date` when known,
    otherwise the soonest day this hotel is bookable.

    Two live-probed facts shape this (MCP_B2C staging, 2026-07-27):
      - `get_hotel_details` without a date returns EVERY upcoming offer (94 of
        them across 32 days for hotel 22293), so a plain global minimum would
        cheerfully quote a cheaper day three weeks out that nobody asked for —
        hence the one-day restriction, always;
      - taking `offers[0]` instead, as this did before, quotes the SOONEST
        bookable day whatever day the user asked for: probing a Paris search
        for J+3, all 5 hotels' `offers[0]` were J+1 offers, and one of them was
        also a different rate plan, slot and price (€80 17:00-22:00 vs the
        card's €70 10:00-18:00). That is the prod defect of 2026-07-27.
    Within a day, "cheapest" is the same rule the card itself applies
    (`response_bridge._best_offer`), mirrored rather than imported (B3: each
    side owns its tiny helpers, like `_hhmm` above)."""
    pool = [o for o in offers if isinstance(o, dict) and not has_unverified_zero_price(o, hotel)]
    if not pool:
        return None
    target = date or min(
        (o["availabilityDate"] for o in pool if o.get("availabilityDate")), default=None
    )
    if target:
        pool = [o for o in pool if o.get("availabilityDate") == target] or pool
    priced = [o for o in pool if display_price_euro(o, hotel) is not None]
    return min(priced, key=lambda o: display_price_euro(o, hotel)) if priced else pool[0]


# S-CX8: how many formulas one booking card may offer. A cap, not a page size:
# each plan costs its own `generate_booking_link` round-trip (they run
# concurrently, but they share the ONE `_INLINE_MCP_TIMEOUT` budget), and a list
# past ~6 rows stops being a choice and becomes a catalogue. Plans are sorted
# cheapest-first before the cut, so what falls off the end is always the
# priciest — never the offer the user was shown.
_MAX_RATE_PLANS = 6


def _hotel_currency_label(
    offer: dict[str, Any], hotel: dict[str, Any] | None
) -> str | None:
    return format_minor_amount(display_price_hotel(offer, hotel), offer.get("hotelCurrency"))


def _rate_plan_view(
    offer: dict[str, Any],
    hotel: dict[str, Any] | None = None,
    display_currency: str | None = None,
) -> dict[str, Any] | None:
    """S-CX8: one MCP offer as a display plan (no link yet — that costs a
    round-trip, added later only for the plans that survive the cut).

    `offer_id` and `date` are REQUIRED — together they are exactly what
    `generate_booking_link` books, so an offer missing either cannot be offered
    as a choice at all. Everything else is only-when-present: the three
    descriptive fields (`ratePlanName`, `roomType`, `addonsIncluded`) are
    REQUESTED from MCP_B2C but not exposed yet (see
    reports/PROMPT-MCP-B2C-RATEPLANS.md), so this must produce a usable row
    from price + slot alone, and gain the labels the day they appear rather
    than needing a second implementation."""
    if has_unverified_zero_price(offer, hotel):
        return None
    offer_id = offer.get("ratePlanUuid")
    offer_date = offer.get("availabilityDate")
    if not (isinstance(offer_id, str) and offer_id.strip()):
        return None
    if not (isinstance(offer_date, str) and offer_date.strip()):
        return None
    # `date` rides on each plan so building its tunnel link needs no outside
    # context. All plans on one card share it by construction
    # (`_day_rate_plans` filters to a single day); the card's own top-level
    # `date` is the selected plan's.
    plan: dict[str, Any] = {"offer_id": offer_id.strip(), "date": offer_date.strip()}
    start = _hhmm(offer.get("startHour"), offer.get("startMinute"))
    end = _hhmm(offer.get("endHour"), offer.get("endMinute"))
    if start and end:
        plan["start_time"] = start
        plan["end_time"] = end
    shown_price = display_price_euro(offer, hotel)
    hotel_label = _hotel_currency_label(offer, hotel) if display_currency == HOTEL else None
    price = hotel_label or _format_price_eur_cents(shown_price)
    if price:
        plan["price"] = price
    cents = _price_eur_cents(shown_price)
    if cents is not None:
        plan["price_eur_cents"] = cents
    # `offerType` is the formula's KIND, and the field that actually tells two
    # plans of one hotel apart. Live-probed 2026-07-28 over 4 596 real offers
    # (51 multi-plan hotels): a closed 5-value enum — dayuse.day 72 %,
    # dayuse.late_break 13 %, dayuse.early 11 %, dayuse.dayuse_pm 3 %,
    # dayuse.dayuse_am 0.7 % — passed through RAW for the widget's own localized
    # table (7 languages), never rendered as-is.
    #
    # It is preferred over `ratePlanName` on evidence, not taste: in the prod
    # catalogue snapshot, 2 829 of 5 591 multi-plan hotels (51 %) give EVERY
    # plan the same `rate_plan_name`, so titling rows with it would show three
    # rows all called "Standard Double Room" — and those names are free text in
    # whatever language the hotelier typed ("Camera doppia standard",
    # "Standard-Doppelzimmer").
    offer_type = offer.get("offerType")
    if isinstance(offer_type, str) and offer_type.strip():
        plan["offer_type"] = offer_type.strip()
    # `ratePlanName` is the ROOM's name, not the formula's (see above). Kept for
    # the widget's last-resort title cascade, never as the primary label.
    name = offer.get("ratePlanName")
    if isinstance(name, str) and name.strip():
        plan["name"] = name.strip()
    # `bedding`/`capacity` are the honest stand-in for "room type": `room_type`
    # is NULL on all 22 177 rows of the prod snapshot, while these two are
    # populated on every probed offer (bedding: double / double_king /
    # double_queen / twin_* / single; capacity: 2 on 92 %). Raw enum again —
    # the widget owns the wording.
    bedding = offer.get("bedding")
    if isinstance(bedding, str) and bedding.strip():
        plan["bedding"] = bedding.strip()
    capacity = offer.get("capacity")
    if isinstance(capacity, int) and capacity > 0:
        plan["capacity"] = capacity
    room_type = offer.get("roomType")
    if isinstance(room_type, str) and room_type.strip():
        plan["room_type"] = room_type.strip()
    # NOTE — there is deliberately no per-plan "included services" here.
    # MCP's `includedAmenities` (added 2026-07-28) looks like the candidate but
    # is HOTEL-level: probed over 227 multi-formula days it was identical across
    # every formula of the day 128 times and different 0 times, with only 4
    # distinct values ever seen (Free parking, Outdoor pool, Indoor pool,
    # Fitness room). Repeating one line on every row while implying it
    # distinguishes them would be a false differentiation, so it rides the CARD
    # instead (`hotel_amenities`, see _day_hotel_amenities).
    # What genuinely varies per formula travels in `ratePlanName` ("Standard
    # Double Room With Meal", "Habitat Room with F&B credit").
    # The night rate this day-use price undercuts. `discount_pct` is computed
    # HERE rather than in the widget so the "-53 %" claim is covered by a test:
    # a discount is a claim, and claims need a guard. Both keys stay absent
    # unless the night rate is a real, strictly higher price than the day rate —
    # a "-0 %" or negative badge would be worse than none.
    # In the hotel's currency, the night rate and the % must be in that currency
    # too, never an EUR night rate struck through next to a HK$ price.
    if hotel_label is not None:
        amount = display_price_hotel(offer, hotel)
        original = offer.get("originalHotelPrice")
        if isinstance(original, int) and isinstance(amount, int) and original > amount > 0:
            plan["original_price"] = format_minor_amount(original, offer.get("hotelCurrency"))
            plan["discount_pct"] = round((original - amount) / original * 100)
        return plan
    original_cents = _price_eur_cents(offer.get("originalPriceEuro"))
    if original_cents is not None and cents is not None and original_cents > cents > 0:
        plan["original_price"] = _format_price_eur_cents(original_cents)
        plan["discount_pct"] = round((original_cents - cents) / original_cents * 100)
    return plan


def _offers_for_day(offers: list[Any], date: str | None) -> list[dict[str, Any]]:
    """The offers of ONE day — the session's `date` when known, else the soonest
    day this hotel is bookable. Shared by the plan list and the card's amenity
    line so the two cannot end up describing different days."""
    pool = [o for o in offers if isinstance(o, dict)]
    target = date or min(
        (o["availabilityDate"] for o in pool if o.get("availabilityDate")), default=None
    )
    if target:
        pool = [o for o in pool if o.get("availabilityDate") == target] or pool
    return pool


def _offers_currency(offers: list[Any]) -> str | None:
    """The hotel's own currency, as its offers carry it (`hotelCurrency`, one
    per hotel)."""
    for offer in offers:
        if isinstance(offer, dict) and isinstance(offer.get("hotelCurrency"), str):
            return str(offer["hotelCurrency"])
    return None


def _day_rate_plans(
    offers: list[Any],
    date: str | None,
    hotel: dict[str, Any] | None = None,
    display_currency: str | None = None,
) -> list[dict[str, Any]]:
    """S-CX8: every bookable formula ON ONE DAY, cheapest first, deduped by
    offer id AND by display signature, capped at `_MAX_RATE_PLANS`.

    Same one-day restriction as `_best_offer`, and for the same live-probed
    reason: `get_hotel_details` without a date returns EVERY upcoming offer (94
    across 32 days for hotel 22293), so an unscoped list would mix next
    Tuesday's formulas into today's choices. Plans without a price sort last
    (still bookable, just not comparable).

    UX4: two MCP offers with different UUIDs can still render as two
    rigorously identical rows — 51% of multi-plan hotels give every formula
    the same `ratePlanName`, `roomType` is NULL everywhere, and `offerType` is
    a 5-value enum, so a type/name/slot collision is structurally common, not
    exotic. If a user can't tell two rows apart on screen, there is no choice
    to offer: dedupe on the display signature `(offer_type, name, start_time,
    end_time, price_eur_cents)` too, keeping the first one encountered — the
    list is sorted cheapest-first below anyway, and duplicates share the same
    price by construction. Price stays IN the signature: two otherwise
    identical formulas at different prices are a real choice."""
    plans: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_signatures: set[tuple[Any, ...]] = set()
    for offer in _offers_for_day(offers, date):
        plan = _rate_plan_view(offer, hotel, display_currency)
        if plan is None or plan["offer_id"] in seen:
            continue
        signature = (
            plan.get("offer_type"),
            plan.get("name"),
            plan.get("start_time"),
            plan.get("end_time"),
            plan.get("price_eur_cents"),
        )
        if signature in seen_signatures:
            continue
        seen.add(plan["offer_id"])
        seen_signatures.add(signature)
        plans.append(plan)
    plans.sort(key=lambda p: (p.get("price_eur_cents") is None, p.get("price_eur_cents") or 0))
    return plans[:_MAX_RATE_PLANS]


def _day_hotel_amenities(offers: list[dict[str, Any]]) -> list[str]:
    """The hotel-level perks MCP attaches to a day's offers (`includedAmenities`,
    exposed 2026-07-28), deduped, order preserved.

    Card-level and not per-plan on evidence: across 227 probed multi-formula days
    the list was identical on every formula 128 times and different 0 times. It
    answers "what comes with a stay here", not "what distinguishes these
    formulas" — so the card states it once."""
    seen: list[str] = []
    for offer in offers:
        for item in offer.get("includedAmenities") or []:
            if isinstance(item, str) and item.strip() and item.strip() not in seen:
                seen.append(item.strip())
    return seen


def _hotel_facts(entry: dict[str, Any] | None) -> dict[str, Any]:
    """The hotel's own display facts, read off its on-screen shortlist entry —
    the photo, page link, city, rating and stars a booking card shows around
    the offer. Never a lookup: a hotel that isn't on screen simply has fewer
    facts (all None), and `_booking_card` drops the empty rows."""
    entry = entry or {}
    return {
        "image_url": (entry.get("image_urls") or [None])[0],
        "hotel_url": entry.get("url"),
        "city": entry.get("city"),
        "rating": entry.get("rating"),
        "rating_count": entry.get("rating_count"),
        "stars": entry.get("stars"),
    }


def _shortlist_entry(hotel_id: int, profile: SessionProfile) -> dict[str, Any] | None:
    """The on-screen shortlist entry for `hotel_id`, or None when that hotel
    isn't on screen."""
    for entry in profile.last_results or []:
        if not isinstance(entry, dict):
            continue
        try:
            if int(entry.get("hotel_id")) == hotel_id:  # type: ignore[arg-type]
                return entry
        except (TypeError, ValueError):
            continue  # an id we can't compare is not a match, never a crash
    return None


def _shortlist_offer(hotel_id: int, profile: SessionProfile) -> dict[str, Any] | None:
    """The stored offer identity for `hotel_id` if the on-screen shortlist
    carries one (`record_search_shortlist`, S-CX5) — the offer the user is
    actually looking at. None when the hotel isn't on screen or its card had
    no offer, which sends the caller to a fresh, date-scoped lookup."""
    entry = _shortlist_entry(hotel_id, profile)
    if entry and entry.get("offer_id") and entry.get("offer_date"):
        return entry
    return None


async def _quote_fresh_offer(
    hotel_reference: str,
    profile: SessionProfile,
    picked_hotel_id: int | None = None,
    authorize_link: bool = False,
    llm_hotel_name: str | None = None,
) -> dict[str, Any]:
    """The confirmed=false branch: resolves the hotel from `hotel_reference`
    (named-hotel lookup guard, item 4) and ALWAYS quotes confirmed=false,
    recording the offer identity in `profile.pending_booking` for a later
    confirmation turn to reuse verbatim.

    `picked_hotel_id` short-circuits that resolution: the spine already knows
    WHICH hotel (S-CX5 — triage understood "le moins cher", `agent.py` picked
    the cheapest of the shortlist in code) and hands the id over rather than a
    phrase to re-interpret. Feeding "le moins cher" to `find_hotel_by_name`
    would fuzzy-match a hotel actually named after those words, or nothing.

    S-CX5 — WHICH offer gets quoted, in order:
      1. the one the shortlist card was priced on (`_shortlist_offer`), reused
         verbatim with no extra MCP round-trip: what the user saw is what they
         book, by construction;
      2. otherwise a fresh `get_hotel_details` **scoped to the session's date**
         (`profile.date`), taking the cheapest offer — the same choice the card
         itself makes.
    Before this, the lookup was unscoped and took `offers[0]`: a card priced
    €87 for 11:00-19:00 tomorrow quoted €90 for 17:00-23:00 today, and the
    tunnel link carried that wrong date (prod session 2026-07-27)."""
    if picked_hotel_id is None and not (hotel_reference or "").strip():
        return {"ok": False, "error": "no hotel reference in the message"}
    try:
        async with asyncio.timeout(_INLINE_MCP_TIMEOUT):
            async with _mcp_session() as session:
                hotel_id: int | None
                hotel_name: str | None
                guards_fired: list[str] = []
                if picked_hotel_id is not None:
                    hotel_id = picked_hotel_id
                    entry = _shortlist_entry(picked_hotel_id, profile)
                    hotel_name = str(entry.get("name")) if entry else None
                else:
                    hotel_id, hotel_name = await _resolve_hotel_id(
                        session, hotel_reference, profile, llm_hotel_name,
                    )
                    guards_fired.append("named_hotel_lookup")
                if hotel_id is None:
                    return {"ok": False, "error": "hotel not found", "guards_fired": guards_fired}
                shown = _shortlist_offer(hotel_id, profile)
                if shown is not None:
                    offer = {
                        "ratePlanUuid": shown["offer_id"],
                        "availabilityDate": shown["offer_date"],
                    }
                    quoted_price = shown.get("price")
                    start_time, end_time = shown.get("start_time"), shown.get("end_time")
                else:
                    args_details: dict[str, Any] = {"hotelId": hotel_id}
                    if profile.date:
                        args_details["date"] = profile.date
                    details = await _call_tool(session, "get_hotel_details", args_details)
                    if not details["ok"]:
                        return {**details, "guards_fired": guards_fired}
                    offers = details["data"].get("offers") or []
                    offers = [o for o in offers if bedding_matches(o, profile.room_requirements)]
                    details_hotel = details["data"].get("hotel")
                    best = _best_offer(offers, profile.date, details_hotel)
                    if best is None:
                        return {
                            "ok": False, "error": "no bookable offer for this hotel",
                            "guards_fired": guards_fired,
                        }
                    offer = best
                    quoted_price = _format_price_eur_cents(display_price_euro(best, details_hotel))
                    if shows_hotel_currency(profile, best.get("hotelCurrency")):
                        quoted_price = _hotel_currency_label(best, details_hotel) or quoted_price
                    start_time = _hhmm(best.get("startHour"), best.get("startMinute"))
                    end_time = _hhmm(best.get("endHour"), best.get("endMinute"))
                identity = {
                    "hotel_id": hotel_id,
                    "hotel_name": hotel_name,
                    "date": offer["availabilityDate"],
                    "rate_plan_uuid": offer.get("ratePlanUuid"),
                    "rate_plan_id": offer.get("ratePlanId"),
                    "start_time": start_time,
                    "end_time": end_time,
                    "price": quoted_price,
                    **_hotel_facts(_shortlist_entry(hotel_id, profile)),
                }
                args: dict[str, Any] = {
                    "hotelId": hotel_id,
                    "date": offer["availabilityDate"],
                    "confirmed": authorize_link,
                }
                if offer.get("ratePlanUuid"):
                    args["ratePlanUuid"] = offer["ratePlanUuid"]
                else:
                    args["ratePlanId"] = offer["ratePlanId"]
                result = await _call_tool(session, "generate_booking_link", args)
                if not result["ok"]:
                    return {**result, "guards_fired": guards_fired}
                if authorize_link:
                    # Nothing left to confirm in a later turn: the card the
                    # caller is about to show carries the link itself.
                    profile.pending_booking = None
                    link = result["data"].get("link") or {}
                    return {
                        **identity, "ok": True, "confirmed": True, "url": link.get("url"),
                        "guards_fired": guards_fired,
                    }
                profile.pending_booking = identity
                return {**identity, "ok": True, "confirmed": False, "guards_fired": guards_fired}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"generate_booking_link failed: {type(exc).__name__}"}


async def _quote_picked_rate_plans(hotel_id: int, profile: SessionProfile) -> dict[str, Any]:
    """S-CX8: the pick turn's card, offering EVERY formula of the chosen day
    instead of only the cheapest one.

    Why this only exists on the pick path: a pick is the one moment the user has
    named a hotel but not yet an offer, so it is the only turn where showing
    siblings is a choice rather than a change of subject. The typed-confirmation
    path (`_confirm_pending_offer`) confirms an offer already quoted and must
    keep reusing it verbatim.

    Which plan is SELECTED by default — the one the shortlist card was priced
    on, NOT the cheapest of the day. The card and the carousel must agree: a
    user who clicked a €87 card and landed on a €70 selection would read it as a
    bait, even though €70 is the better deal. The cheapest is only the fallback
    when the shortlist carries no offer identity (`_day_rate_plans` already
    sorted cheapest-first, so that is `plans[0]`).

    Returns `{"ok": False, ...}` to mean "fall back to the single-offer path" —
    every degradation (details call down, no priced offer, the selected plan's
    own link failing) lands there, so this can only ever ADD a choice, never
    replace the working card with a broken one."""
    try:
        async with asyncio.timeout(_INLINE_MCP_TIMEOUT):
            async with _mcp_session() as session:
                args_details: dict[str, Any] = {"hotelId": hotel_id}
                if profile.date:
                    args_details["date"] = profile.date
                details = await _call_tool(session, "get_hotel_details", args_details)
                if not details["ok"]:
                    return details
                offers = details["data"].get("offers") or []
                offers = [o for o in offers if bedding_matches(o, profile.room_requirements)]
                plans = _day_rate_plans(
                    offers, profile.date, details["data"].get("hotel"),
                    HOTEL if shows_hotel_currency(profile, _offers_currency(offers)) else None,
                )
                if not plans:
                    return {"ok": False, "error": "no bookable offer for this hotel"}
                amenities = _day_hotel_amenities(_offers_for_day(offers, profile.date))

                shown = _shortlist_offer(hotel_id, profile)
                shown_id = shown.get("offer_id") if shown else None
                selected = next((p for p in plans if p["offer_id"] == shown_id), plans[0])

                # Concurrent on ONE session on purpose: the plans share a single
                # `_INLINE_MCP_TIMEOUT` budget, so N sequential link calls would
                # spend it N times over. Safe by construction — the MCP SDK's
                # `BaseSession.send_request` stamps each request with a
                # monotonic id and awaits its own response stream
                # (`_response_streams[request_id]`), so responses cannot be
                # crossed; the id is assigned with no await in between.
                links = await asyncio.gather(
                    *(
                        _call_tool(
                            session,
                            "generate_booking_link",
                            {
                                "hotelId": hotel_id,
                                "date": plan["date"],
                                "ratePlanUuid": plan["offer_id"],
                                "confirmed": True,
                            },
                        )
                        for plan in plans
                    )
                )
                # A plan whose link failed is DROPPED: a row the user can select
                # but not book is worse than a row that was never offered.
                bookable: list[dict[str, Any]] = []
                for plan, link_result in zip(plans, links, strict=True):
                    if not link_result["ok"]:
                        continue
                    url = ((link_result["data"] or {}).get("link") or {}).get("url")
                    if url:
                        bookable.append({**plan, "url": url})
                selected_bookable = next(
                    (p for p in bookable if p["offer_id"] == selected["offer_id"]), None
                )
                if selected_bookable is None:
                    return {"ok": False, "error": "selected offer has no bookable link"}

                entry = _shortlist_entry(hotel_id, profile)
                identity: dict[str, Any] = {
                    "ok": True,
                    "confirmed": True,
                    "hotel_id": hotel_id,
                    "hotel_name": str(entry.get("name")) if entry else None,
                    "url": selected_bookable["url"],
                    "date": selected_bookable["date"],
                    "start_time": selected_bookable.get("start_time"),
                    "end_time": selected_bookable.get("end_time"),
                    "price": selected_bookable.get("price"),
                    **_hotel_facts(entry),
                }
                if amenities:
                    identity["hotel_amenities"] = amenities
                # One formula is not a choice: the card stays exactly today's.
                if len(bookable) > 1:
                    identity["rate_plans"] = [
                        {**p, "selected": p["offer_id"] == selected_bookable["offer_id"]}
                        for p in bookable
                    ]
                profile.pending_booking = None  # the card carries its own links
                return identity
    except Exception as exc:  # noqa: BLE001 — degrade to the single-offer path
        return {"ok": False, "error": f"rate plan quote failed: {type(exc).__name__}"}


async def generate_booking_link(
    hotel_reference: str,
    profile: SessionProfile,
    user_confirmed: bool,
    picked_hotel_id: int | None = None,
    llm_hotel_name: str | None = None,
) -> dict[str, Any]:
    with observation(as_type="guardrail", name="authorize-booking-link"):
        return await _generate_booking_link_impl(
            hotel_reference, profile, user_confirmed, picked_hotel_id, llm_hotel_name
        )


async def _generate_booking_link_impl(
    hotel_reference: str,
    profile: SessionProfile,
    user_confirmed: bool,
    picked_hotel_id: int | None = None,
    llm_hotel_name: str | None = None,
) -> dict[str, Any]:
    """R9 / guard #12. `generate_booking_link` is stateless server-side (a
    bare `confirmed=true` call returns a real link with no memory of any
    prior round-trip — verified against MCP_B2C staging) so the authorization
    lives entirely HERE, in code. It is NEVER derived from what the caller
    asserts, and never from an LLM's judgment.

    S-CX5 — what authorizes a link, decided with Fabien (2026-07-27). The
    invariant is unchanged: a link needs an explicit, code-owned confirmation
    flag in the turn state. What SATISFIES it now has two forms:
      a. `profile.pending_booking` + `user_confirmed` — the original flow: a
         quote was shown last turn and this turn is a bare "yes".
      b. `picked_hotel_id` — the spine resolved WHICH hotel from an explicit
         user selection (a pick button, or a message triage read as pointing
         at one hotel on screen) on a turn already classified as booking. The
         reply is a card STATING the hotel, day, slot and price next to the
         button that opens the tunnel, so the user still sees exactly what
         they are about to book — strictly more than a typed "yes" under a
         sentence showed them. This removes the "do you confirm?" turn.
      Nothing is booked by either: the link opens the Dayuse tunnel, where
      payment still happens.

    Flow:
      1. `picked_hotel_id` set -> resolve the offer and return it WITH the
         link (`authorize_link=True`), leaving no pending booking behind.
         S-CX8: tried FIRST as a multi-formula card (`_quote_picked_rate_plans`
         — every rate plan of that day, each with its own link, the shortlist's
         offer pre-selected); any degradation falls through to the single-offer
         path below, which is unchanged.
      2. No pending offer (or `user_confirmed` False) -> quotes
         confirmed=false (`_quote_fresh_offer`), resolving the hotel from
         `hotel_reference`. Records the offer identity in
         `profile.pending_booking` so a later bare "yes" confirms THAT exact
         offer without re-resolving anything from the "yes" itself.
      3. A pending offer exists AND `user_confirmed` -> confirms it
         (`_confirm_pending_offer`), reusing the stored identity verbatim —
         UNLESS `hotel_reference` names, or `picked_hotel_id` is, a DIFFERENT
         hotel (defense in depth: a caller asserting confirmed=true while
         pointing at another hotel must not confirm the stale one — it
         re-resolves the newly named one instead).
    """
    if profile.pending_party_total is not None:
        # PORT1 slice 5: no link for a party whose adults/children are unknown.
        profile.pending_booking = None
        return {"ok": False, "error": "party_composition_required"}
    pending = profile.pending_booking
    if user_confirmed and pending is not None:
        named_hit = resolve_hotel_reference(hotel_reference or "", profile.last_results)
        mismatch = (
            named_hit is not None
            and named_hit.get("hotel_id") is not None
            and int(named_hit["hotel_id"]) != pending.get("hotel_id")
        ) or (picked_hotel_id is not None and picked_hotel_id != pending.get("hotel_id"))
        if mismatch:
            mark_level("WARNING", status_message="booking_confirmation_mismatch")
        if not mismatch:
            profile.pending_booking = None
            result = await _confirm_pending_offer(pending)
            if not result["ok"]:
                profile.pending_booking = pending  # confirmation failed: keep the offer quotable
            return result

    if picked_hotel_id is not None:
        # S-CX8: the pick turn earns the formula selector. Not-ok here means
        # "degrade", never "fail the turn" — the single-offer path below is the
        # same code that has always served this case.
        multi = await _quote_picked_rate_plans(picked_hotel_id, profile)
        if multi.get("ok"):
            return multi

    return await _quote_fresh_offer(
        hotel_reference,
        profile,
        picked_hotel_id,
        authorize_link=picked_hotel_id is not None,
        llm_hotel_name=llm_hotel_name,
    )
