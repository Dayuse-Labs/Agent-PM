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
    if not hotels:
        if profile.consecutive_empty_searches > 0:
            return "\n\n## CURRENT RESULTS (GROUND TRUTH)\n" + _EMPTY_SCREEN_NOTE
        return ""
    lines = [_hotel_line(hotel) for hotel in hotels]
    return "\n\n## CURRENT SHORTLIST (GROUND TRUTH)\n" + _HEADER + "\n".join(lines)
