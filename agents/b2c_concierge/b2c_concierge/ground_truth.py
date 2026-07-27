"""Ground-truth block for the b2c-concierge synthesis prompt (S06).

Anchors the synthesis LLM to what THIS turn's leaf search actually returned —
the same class of prod defect agent-usa's ground-truth block fixed: an LLM
asserting "I haven't searched yet" or inventing hotel details not present in
the outcome. Unlike agent-usa (a long-lived `Conversation.preferences` that
keeps a `last_results` shortlist alive across turns, including empty ones),
this spine has no such carry-over: `response["results"]` is only ever THIS
turn's own leaf outcome (contract.py, SearchResponse — never fabricated), so
a stale shortlist describing an earlier turn while the current screen is
empty cannot happen here by construction — the empty-screen note only ever
applies to the "no results" branch, never alongside a real shortlist.
"""
from __future__ import annotations

from typing import Any

from .profile import SessionProfile

# ≤5 hotels / capped amenities per hotel — bounds the prompt, keeps the block
# cache-friendly (S06 phase spec): the leaf's own instruction already asks for
# a top-5, small payload; this is the deterministic backstop.
MAX_HOTELS = 5
MAX_AMENITIES = 8

_EMPTY_SCREEN_NOTE = (
    "NOTE: the MOST RECENT search returned ZERO results, so the user "
    "currently sees NO hotel cards. If the user says they see no list, that "
    "is correct — acknowledge it and offer a concrete way to adjust the "
    "search instead of suggesting a display or refresh problem. STATE PLAINLY "
    "what was searched using the SEARCH CONTEXT and the date in the MESSAGE "
    "(e.g. \"no day-use offers in <place> for <date>\"), then propose ONE "
    "concrete next step: change the date, widen the area, or adjust the budget.\n"
)

# S-CX6: same-day dead end. Every day-use offer's booking cutoff falls on the
# stay date itself (measured: 05h→16h local, latest 16h), so an afternoon search
# dated today returns zero for an entire market that has hundreds of hotels.
# The generic note above sent users off widening a zone that was never the
# problem; this one names the cause and points at the only thing that fixes it.
_SAME_DAY_CLOSED_NOTE = (
    "CAUSE (authoritative, state it): the search ran for TODAY ({date}) and "
    "same-day day-use bookings are already CLOSED for this market — each offer "
    "stops being bookable during the stay day itself (latest around 16:00 "
    "local). This is NOT an empty city, NOT a budget problem, NOT a zone "
    "problem: hotels exist there, today's booking window has simply passed. "
    "Say that plainly, then offer ANOTHER DAY (tomorrow first) as the next "
    "step. Do NOT suggest widening the area, raising the budget or removing a "
    "filter — none of them can reopen a closed day.\n"
)

# S-CX6: the probe found a bookable next day and those cards ARE on screen —
# they are simply not for the day the user implicitly asked for. Presenting
# them as today's would be worse than the dead end this replaced.
_DATE_FALLBACK_NOTE = (
    "MANDATORY DISCLOSURE: the hotels listed below are for {offered}, NOT for "
    "today ({searched}). Same-day bookings were already closed, so the search "
    "was re-run for the next day. Your FIRST sentence must say that today is "
    "closed and that these offers are for {offered}. Never imply they are "
    "available today.\n"
)


def date_context_block(response: dict[str, Any] | None) -> str:
    """S-CX6: the date-truth prelude to the shortlist/empty block. Driven by the
    leaf's `search_date` DataPart key (`date` / `same_day` /
    `cutoff_fallback_from`) — the concierge cannot derive any of it: a
    carried-over or defaulted date is deliberately never persisted to the
    profile, which is exactly why the old dead-end answer never named the day
    it had searched."""
    search_date = (response or {}).get("search_date")
    if not isinstance(search_date, dict):
        return ""
    offered = search_date.get("date")
    if not isinstance(offered, str) or not offered:
        return ""
    searched = search_date.get("cutoff_fallback_from")
    if isinstance(searched, str) and searched:
        return _DATE_FALLBACK_NOTE.format(offered=offered, searched=searched)
    # `cutoff_closed` — NOT `same_day` alone: the leaf only sets it when hotels
    # matched and none was bookable. A same-day zero over an empty pool is a
    # market without day-use inventory, and blaming a closed booking window
    # there would be an invented cause (the generic note handles it).
    if search_date.get("cutoff_closed") and not shortlist_hotels(response):
        return _SAME_DAY_CLOSED_NOTE.format(date=offered)
    return f"SEARCH DATE: these results are for {offered}. State that date.\n"

_HEADER = (
    "A live Dayuse search ALREADY ran this turn and returned the hotels "
    "below. Never claim that no search has been run. Any detail you state "
    "about these hotels (amenities, price, location) MUST come from this "
    "list — if something is not listed here, say it is not listed instead "
    "of asserting or inventing it.\n"
    "IMPORTANT: this block is reference data for truthfulness only — it "
    "does NOT replace tool calls. If the user changes any constraint or "
    "asks to see options again, a fresh search is still required; describing "
    "these hotels from memory instead of running a new search is a failure.\n"
    "LINKS: when giving a link to a hotel, copy EXACTLY the url listed for "
    "it below — NEVER construct, guess, translate, or edit a URL yourself "
    "(the real slug and domain are not derivable from the hotel name). A "
    "hotel with no url listed has no link to give: say so.\n"
)


def _hotel_line(hotel: dict[str, Any]) -> str:
    name = str(hotel.get("name") or "").strip() or "?"
    place = str(hotel.get("city") or hotel.get("address") or "").strip()
    price = str(hotel.get("price") or "").strip()
    amenities = [str(a) for a in (hotel.get("amenities") or []) if str(a).strip()][:MAX_AMENITIES]
    amenity_text = ", ".join(amenities) or "none listed"
    line = f"- {name}"
    if place:
        line += f" ({place})"
    if price:
        line += f" — {price}"
    line += f" — amenities: {amenity_text}"
    rating = hotel.get("rating")
    if isinstance(rating, (int, float)):
        line += f" — rating {float(rating):.1f}/5"
    url = hotel.get("url")
    if isinstance(url, str) and url.startswith("https://"):
        line += f" — url: {url}"
    return line


def shortlist_hotels(response: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The same bounded hotel list the ground-truth block renders — shared
    with the amenity-claim verifier (S07, amenity_guard.py) so it checks the
    synthesis text against EXACTLY the hotels the LLM was grounded in,
    whatever the response's source (search leaf, or an S07 inline tool
    shaped the same way: `{"results": [...]}`)."""
    results = (response or {}).get("results")
    return [h for h in (results or []) if isinstance(h, dict)][:MAX_HOTELS]


def shortlist_ground_truth_block(response: dict[str, Any] | None, profile: SessionProfile) -> str:
    """System-prompt block anchoring the synthesis LLM to this turn's search
    outcome. Empty string when there is nothing to ground (no leaf results and
    no empty-search streak yet) — never adds an empty section to the prompt."""
    hotels = shortlist_hotels(response)
    date_block = date_context_block(response)
    if not hotels:
        if profile.consecutive_empty_searches > 0:
            # Date block LAST on this path: it is the authoritative cause and
            # must override the generic note's "widen the area / adjust the
            # budget" menu when the real reason is a closed same-day window.
            return "\n\n## CURRENT RESULTS (GROUND TRUTH)\n" + _EMPTY_SCREEN_NOTE + date_block
        return ""
    lines = [_hotel_line(hotel) for hotel in hotels]
    return "\n\n## CURRENT SHORTLIST (GROUND TRUTH)\n" + date_block + _HEADER + "\n".join(lines)
