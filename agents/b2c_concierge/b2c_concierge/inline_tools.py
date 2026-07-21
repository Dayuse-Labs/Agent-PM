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
import os
import re
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .profile import (
    SessionProfile,
    resolve_hotel_reference,
    resolve_hotel_reference_strict,
    resolve_hotel_references,
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
    never an invented result."""
    try:
        result = await session.call_tool(name, arguments)
    except Exception as exc:  # noqa: BLE001 — an MCP failure degrades, never crashes
        return {"ok": False, "error": f"{name} failed: {type(exc).__name__}"}
    if result.isError:
        message = "".join(getattr(c, "text", "") for c in (result.content or [])) or f"{name}: tool error"
        return {"ok": False, "error": message}
    if result.structuredContent is not None:
        return {"ok": True, "data": result.structuredContent}
    return {"ok": False, "error": f"{name}: no structured response"}



# MCP `find_hotel_by_name` matches "partial input and typos", NOT a whole
# sentence around the name (verified live: "Book Villa Paris Orly for me" ->
# HotelNotFoundError, "Villa Paris Orly" -> a match) — no LLM entity
# extraction runs in this spine, so a lightweight, deterministic strip of the
# common request phrasing is the fallback's OWN best-effort extraction
# before calling MCP. The shortlist fuzzy-match (`resolve_hotel_reference`,
# checked FIRST, above) needs no such extraction — it already tolerates the
# full sentence by design, so this heuristic only matters for a hotel named
# but not currently on screen.
_LEADING_REQUEST_PHRASES_RE = re.compile(
    r"^(?:please\s+)?(?:book|reserve|r[ée]serve[rz]?|compare|"
    r"(?:show|tell)\s+me\s+(?:more\s+)?(?:details\s+)?(?:on|for|about)|"
    r"details?\s+(?:on|for|about)|what\s+about)\s+(?:the\s+)?",
    re.IGNORECASE,
)
_TRAILING_REQUEST_PHRASES_RE = re.compile(
    r"\s+(?:for\s+me|please|s'il\s+vous\s+pla[iî]t|svp|now|today|merci)\.?\s*$",
    re.IGNORECASE,
)


def _extract_hotel_name_candidate(text: str) -> str:
    """Best-effort strip of common request phrasing around a hotel name.
    Falls back to `text` unchanged if nothing was stripped (never returns an
    empty string when `text` itself isn't empty)."""
    candidate = _LEADING_REQUEST_PHRASES_RE.sub("", text.strip()).strip()
    candidate = _TRAILING_REQUEST_PHRASES_RE.sub("", candidate).strip()
    return candidate or text.strip()


async def _resolve_hotel_id(
    session: ClientSession, reference: str, profile: SessionProfile
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
    strong_hit = resolve_hotel_reference_strict(reference, profile.last_results)
    if strong_hit is not None and strong_hit.get("hotel_id") is not None:
        return int(strong_hit["hotel_id"]), str(strong_hit["name"])

    args: dict[str, Any] = {"name": _extract_hotel_name_candidate(reference)}
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


def _format_price_eur_cents(cents: Any) -> str | None:
    """P3 (AUDIT-REWORK-2026-07.md): `priceEuro` is EUR cents; devise du user
    si connue sinon EUR. This profile carries no user-currency signal today
    (nothing upstream ever captures one), so display is always EUR — the
    simple, honest default the phase pre-approved; revisit if a user-currency
    preference is ever captured."""
    if cents is None:
        return None
    try:
        return f"€{float(cents) / 100:.2f}"
    except (TypeError, ValueError):
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
        "stars": hotel.get("starRating"),
        "amenities": _flatten_amenities(hotel.get("amenities")),
    }
    photo = _photo_url(hotel.get("mainPhotoNormal"))
    if photo:
        normalized["image_urls"] = [photo]
    if best_offer:
        normalized["price"] = _format_price_eur_cents(best_offer.get("priceEuro"))
    return normalized


# --- Public inline tools ------------------------------------------------------------------------


async def get_hotel_details(hotel_reference: str, profile: SessionProfile) -> dict[str, Any]:
    """Real MCP_B2C `get_hotel_details`, hotel resolved via the named-hotel
    lookup guard. Returns `{"ok": True, "hotel": {...normalized...}}` or
    `{"ok": False, "error": ...}` — never raises, never invents."""
    if not (hotel_reference or "").strip():
        return {"ok": False, "error": "no hotel reference in the message"}
    try:
        async with asyncio.timeout(_INLINE_MCP_TIMEOUT):
            async with _mcp_session() as session:
                hotel_id, _ = await _resolve_hotel_id(session, hotel_reference, profile)
                if hotel_id is None:
                    return {"ok": False, "error": "hotel not found"}
                result = await _call_tool(session, "get_hotel_details", {"hotelId": hotel_id})
                if not result["ok"]:
                    return result
                data = result["data"]
                hotel = data.get("hotel") or {}
                offers = data.get("offers") or []
                normalized = _normalize_hotel_for_display(hotel, offers[0] if offers else None)
                return {"ok": True, "hotel": normalized}
    except Exception as exc:  # noqa: BLE001 — degrade honestly, never crash the turn
        return {"ok": False, "error": f"get_hotel_details failed: {type(exc).__name__}"}


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
                return {"ok": True, "confirmed": True, "url": link.get("url"), "hotel_name": pending.get("hotel_name")}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"generate_booking_link failed: {type(exc).__name__}"}


async def _quote_fresh_offer(hotel_reference: str, profile: SessionProfile) -> dict[str, Any]:
    """The confirmed=false branch: resolves the hotel from `hotel_reference`
    (named-hotel lookup guard, item 4) and ALWAYS quotes confirmed=false,
    recording the offer identity in `profile.pending_booking` for a later
    confirmation turn to reuse verbatim."""
    if not (hotel_reference or "").strip():
        return {"ok": False, "error": "no hotel reference in the message"}
    try:
        async with asyncio.timeout(_INLINE_MCP_TIMEOUT):
            async with _mcp_session() as session:
                hotel_id, hotel_name = await _resolve_hotel_id(session, hotel_reference, profile)
                if hotel_id is None:
                    return {"ok": False, "error": "hotel not found"}
                details = await _call_tool(session, "get_hotel_details", {"hotelId": hotel_id})
                if not details["ok"]:
                    return details
                offers = details["data"].get("offers") or []
                if not offers:
                    return {"ok": False, "error": "no bookable offer for this hotel"}
                offer = offers[0]
                args: dict[str, Any] = {
                    "hotelId": hotel_id,
                    "date": offer["availabilityDate"],
                    "confirmed": False,
                }
                if offer.get("ratePlanUuid"):
                    args["ratePlanUuid"] = offer["ratePlanUuid"]
                else:
                    args["ratePlanId"] = offer["ratePlanId"]
                result = await _call_tool(session, "generate_booking_link", args)
                if not result["ok"]:
                    return result
                profile.pending_booking = {
                    "hotel_id": hotel_id,
                    "hotel_name": hotel_name,
                    "date": offer["availabilityDate"],
                    "rate_plan_uuid": offer.get("ratePlanUuid"),
                    "rate_plan_id": offer.get("ratePlanId"),
                }
                return {
                    "ok": True,
                    "confirmed": False,
                    "hotel_name": hotel_name,
                    "date": offer["availabilityDate"],
                    "start_hour": offer.get("startHour"),
                    "end_hour": offer.get("endHour"),
                    "price": _format_price_eur_cents(offer.get("priceEuro")),
                }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"generate_booking_link failed: {type(exc).__name__}"}


async def generate_booking_link(
    hotel_reference: str, profile: SessionProfile, user_confirmed: bool
) -> dict[str, Any]:
    """R9 / guard #12. `generate_booking_link` is stateless server-side (a
    bare `confirmed=true` call returns a real link with no memory of any
    prior round-trip — verified against MCP_B2C staging) so the confirmation
    guarantee lives entirely HERE: MCP is only ever called with
    `confirmed=true` when `profile.pending_booking` is already set — never
    from whatever `user_confirmed` alone asserts.

    Flow:
      1. No pending offer (or `user_confirmed` False) -> ALWAYS quotes
         confirmed=false (`_quote_fresh_offer`), resolving the hotel from
         `hotel_reference` — a fresh request. Records the offer identity in
         `profile.pending_booking` so a later bare "yes" can confirm THIS
         exact offer without re-resolving anything from that "yes" itself.
      2. A pending offer exists AND `user_confirmed` -> confirms it
         (`_confirm_pending_offer`), reusing the stored identity verbatim —
         UNLESS `hotel_reference` itself names a DIFFERENT hotel already on
         the shortlist (defense in depth: a caller asserting confirmed=true
         while explicitly naming another hotel must not confirm the stale
         one — it re-quotes the newly named hotel instead, confirmed=false).
    """
    pending = profile.pending_booking
    if user_confirmed and pending is not None:
        named_hit = resolve_hotel_reference(hotel_reference or "", profile.last_results)
        mismatch = (
            named_hit is not None
            and named_hit.get("hotel_id") is not None
            and int(named_hit["hotel_id"]) != pending.get("hotel_id")
        )
        if not mismatch:
            profile.pending_booking = None
            result = await _confirm_pending_offer(pending)
            if not result["ok"]:
                profile.pending_booking = pending  # confirmation failed: keep the offer quotable
            return result

    return await _quote_fresh_offer(hotel_reference, profile)
