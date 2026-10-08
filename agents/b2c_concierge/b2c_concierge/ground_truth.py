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

from datetime import date, time
from typing import Any

from b2c_common import minor_units
from b2c_common.timeslot import parse_hhmm

from .date_format import format_date_human
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
    "search instead of suggesting a display or refresh problem. When a NO OFFERS sentence "
    "is present it already states what was searched: do not repeat it. "
    "Otherwise STATE PLAINLY what was searched using the SEARCH CONTEXT and the date in the MESSAGE "
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


def date_context_block(response: dict[str, Any] | None, language: str = "en") -> str:
    """S-CX6: the date-truth prelude to the shortlist/empty block. Driven by the
    leaf's `search_date` DataPart key (`date` / `same_day` /
    `cutoff_fallback_from`) — the concierge cannot derive any of it: a
    carried-over or defaulted date is deliberately never persisted to the
    profile, which is exactly why the old dead-end answer never named the day
    it had searched.

    Dates reach the prompt already written out in the turn's `language`
    (`date_format.format_date_human`): an ISO date here was copied verbatim
    into user-facing replies ("Pour demain (2026-09-24)…", QA 2026-09-08)."""
    search_date = (response or {}).get("search_date")
    if not isinstance(search_date, dict):
        # Inline named-hotel/details results do not always carry the leaf's
        # search_date envelope. Only actual dated offers can establish it;
        # a property identity or the requested profile date is not evidence.
        hotels = shortlist_hotels(response)
        dates = [h.get("offer_date") for h in hotels
                 if h.get("offer_id") and h.get("timeslots")]
        if not hotels or len(dates) != len(hotels) or not all(isinstance(d, str) for d in dates):
            return ""
        unique_dates = set(dates)
        if len(unique_dates) != 1:
            return ""
        offered_date = dates[0]
        if not isinstance(offered_date, str):
            return ""
        try:
            date.fromisoformat(offered_date)
        except (ValueError, TypeError):
            return ""
        search_date = {"date": offered_date}
    offered = search_date.get("date")
    if not isinstance(offered, str) or not offered:
        return ""
    offered_human = format_date_human(offered, language)
    searched = search_date.get("cutoff_fallback_from")
    if isinstance(searched, str) and searched:
        return _DATE_FALLBACK_NOTE.format(
            offered=offered_human, searched=format_date_human(searched, language)
        )
    # `cutoff_closed` — NOT `same_day` alone: the leaf only sets it when hotels
    # matched and none was bookable. A same-day zero over an empty pool is a
    # market without day-use inventory, and blaming a closed booking window
    # there would be an invented cause (the generic note handles it).
    if search_date.get("cutoff_closed") and not shortlist_hotels(response):
        return _SAME_DAY_CLOSED_NOTE.format(date=offered_human)
    return (
        f"SEARCH DATE: these results are for {offered_human}. State that date "
        "in this written-out form — never as YYYY-MM-DD. State it even on a "
        "named-hotel follow-up: the previous search may have served another day.\n"
    )

_HEADER = (
    "A live Dayuse search ALREADY ran this turn and returned the hotels "
    "below. Never claim that no search has been run. Any detail you state "
    "about these hotels (amenities, price, location) MUST come from this "
    "list — if something is not listed here, do NOT assert or invent it. "
    "Only SAY that a detail is missing when the user actually asked about "
    "it: volunteering \"the amenities are not listed\" on a turn where "
    "nobody asked is filler that reads as a malfunction (prod 2026-07-29).\n"
    "IMPORTANT: this block is reference data for truthfulness only — it "
    "does NOT replace tool calls. If the user changes any constraint or "
    "asks to see options again, a fresh search is still required; describing "
    "these hotels from memory instead of running a new search is a failure.\n"
    "LINKS: when giving a link to a hotel, copy EXACTLY the url listed for "
    "it below — NEVER construct, guess, translate, or edit a URL yourself "
    "(the real slug and domain are not derivable from the hotel name). A "
    "hotel with no url listed has no link to give: say so.\n"
)


def _minute_coverage(hotel: dict[str, Any], window: dict[str, str | None] | None) -> str:
    """Evidence for wording only; never override the site's rounded-hour filter."""
    def clock(value: Any) -> int | None:
        if not isinstance(value, str) or len(value) != 5:
            return None
        minutes = parse_hhmm(value)
        return minutes if minutes is not None and minutes <= 1440 else None

    window = window or {}
    start, end = clock(window.get("start")), clock(window.get("end"))
    if start is None or end is None:
        return ""
    if end == 0 and start > 0:
        end = 1440
    if end <= start:
        return ""  # No inferred overnight date or duration.
    valid_slots = []
    for slot in (hotel.get("timeslots") or [])[:5]:
        if not isinstance(slot, dict):
            continue
        left, right = clock(slot.get("start")), clock(slot.get("end"))
        if left is None or right is None:
            continue
        if right == 0 and left > 0:
            right = 1440
        if right > left:
            valid_slots.append((left, right))
    covers = any(left <= start and right >= end for left, right in valid_slots)
    verdict = "covered" if covers else "not covered" if valid_slots else "unknown"
    return f" — minute coverage of {window['start']}–{window['end']}: {verdict}"


def _hotel_line(hotel: dict[str, Any], window: dict[str, str | None] | None = None) -> str:
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
    # Expose the same dated slot the card shows. A requested profile window
    # is not proof of an available offer, and must never fill missing data.
    offered_date = hotel.get("offer_date")
    if isinstance(offered_date, str):
        try:
            date.fromisoformat(offered_date)
        except ValueError:
            pass
        else:
            line += f" — offer date: {offered_date}"
    slots = []
    for slot in (hotel.get("timeslots") or [])[:5]:
        if not isinstance(slot, dict):
            continue
        start, end = slot.get("start"), slot.get("end")
        if not isinstance(start, str) or not isinstance(end, str) or len(start) != 5 or len(end) != 5:
            continue
        try:
            time.fromisoformat(start)
            time.fromisoformat(end)
        except ValueError:
            continue
        slots.append(f"{start}–{end}")
    if slots:
        line += " — offered times: " + ", ".join(slots)
    line += _minute_coverage(hotel, window)
    line += f" — amenities: {amenity_text}"
    rating = hotel.get("rating")
    if isinstance(rating, (int, float)):
        line += f" — rating {float(rating):.1f}/5"
    url = hotel.get("url")
    if isinstance(url, str) and url.startswith("https://"):
        line += f" — url: {url}"
    return line


def _price_cents(hotel: dict[str, Any]) -> int | None:
    value = hotel.get("price_eur_cents")
    return value if isinstance(value, int) and value > 0 else None


def _shown_price(hotel: dict[str, Any]) -> tuple[float, str] | None:
    """The price the card DISPLAYS, in major units, with its currency: the
    hotel-currency one after `display_currency.apply_hotel_currency`, else EUR.
    The slot's `original_price` is always in that same currency."""
    code = hotel.get("display_currency")
    minor = hotel.get("display_price_minor")
    if isinstance(code, str) and isinstance(minor, int) and minor > 0:
        return minor / 10 ** minor_units(code), code
    cents = _price_cents(hotel)
    return (cents / 100, "EUR") if cents else None


def _first_slot(hotel: dict[str, Any]) -> dict[str, Any]:
    slot = (hotel.get("timeslots") or [None])[0]
    return slot if isinstance(slot, dict) else {}


def synthesis_angle(response: dict[str, Any] | None, exclude: str = "") -> tuple[str, str]:
    """`(key, directive)` — the ONE fact worth leading this turn's reply on,
    picked in CODE from the shortlist. `("", "")` when the data says nothing
    notable, and the model then just writes short.

    `exclude` is the key used on the PREVIOUS turn of this session, and it is
    skipped. Without it the feature defeats itself: two consecutive searches
    that keep the same top hotel produce the same angle, so the reply reads
    almost verbatim twice (observed in the browser 2026-07-29 — "économie
    impressionnante … 66 %" twice in a row). Falling through to the next
    candidate — or to no angle at all — is what makes consecutive turns differ.

    Why code and not the model: asked for a "warm, concise" reply over the same
    fields every turn, an LLM produces the same reply every turn (prod
    2026-07-29: a 930-char list of the exact cards already on screen, opener
    included). Variety has to come from the DATA, not from temperature — a
    turn where the cheapest option is half the price of the others genuinely
    warrants a different sentence than one where every hotel is 12 km out.
    Deterministic by construction: same shortlist in, same angle out, so it is
    testable and can never become a random-tone generator.

    Ordered by how much the fact changes the user's decision, first match wins.
    Every angle names only what the cards ALREADY show, so it can add no claim
    the guards would have to catch — it re-frames, it never introduces."""
    hotels = shortlist_hotels(response)
    if not hotels:
        return ("", "")

    candidates: list[tuple[str, str]] = []

    if len(hotels) == 1:
        candidates.append((
            "single",
            "The current result contains one hotel. This can be a selected "
            "hotel's details or one page of a search, not exhaustive inventory. "
            "Do not claim it is the only matching hotel or push wider filters "
            "merely because one card is present.",
        ))

    # Out-of-centre: the single most useful thing the cards bury — each card
    # shows its own district in small type, so "all five are in the suburbs"
    # is invisible until you read all five.
    distances = [h["distance_km"] for h in hotels
                 if isinstance(h.get("distance_km"), (int, float))]
    if len(distances) >= 2 and min(distances) >= 6:
        candidates.append((
            "distance",
            f"The displayed distances are {min(distances):.0f}-"
            f"{max(distances):.0f} km from the search origin. This does not prove "
            "the hotels are outside the city, quiet, or unsuitable. The origin "
            "may be a landmark, not the centre. Offer a closer search only if "
            "the customer's stated preference calls for it.",
        ))

    # Deep discount: commercially the strongest line, and the badge on the card
    # states the percentage without saying which hotel carries the best one.
    discounts = []
    for hotel in hotels:
        shown, was = _shown_price(hotel), _first_slot(hotel).get("original_price")
        if shown and isinstance(was, (int, float)) and was > 0:
            pct = round(100 - shown[0] / float(was) * 100)
            if pct > 0:
                discounts.append((pct, str(hotel.get("name") or "")))
    if discounts:
        best_pct, best_name = max(discounts)
        if best_pct >= 40:
            candidates.append((
                "discount",
                f"{best_name} is about {best_pct}% below its night rate. "
                "This is a relative discount, not proof it is the cheapest "
                "or the best fit for the customer's purpose. Use only if relevant.",
            ))

    # Price spread: "the cheapest" is answerable by eye on the cards, but how
    # much cheaper is not.
    shown_prices = [p for p in (_shown_price(h) for h in hotels) if p]
    prices = [amount for amount, _ in shown_prices]
    codes = {code for _, code in shown_prices}
    if len(prices) >= 2 and len(codes) == 1 and min(prices) <= 0.7 * max(prices):
        unit = "€" if codes == {"EUR"} else next(iter(codes))
        candidates.append((
            "spread",
            f"Wide price spread: {int(min(prices))}-{int(max(prices))} {unit} "
            "across the shortlist. A higher price alone does not prove better "
            "location, quality or included services. Respect a lowest-price request.",
        ))

    # Thin review base: an honesty caveat, and the one the card cannot make.
    rated = [h for h in hotels if isinstance(h.get("rating"), (int, float)) and h["rating"] > 0]
    if rated and all(
        isinstance(h.get("rating_count"), int) and h["rating_count"] <= 2 for h in rated
    ):
        candidates.append((
            "thin_ratings",
            "Every score here rests on 1-2 reviews. Mention plainly that the "
            "ratings are too thin to rank on, and suggest judging on location "
            "or price instead.",
        ))

    for key, directive in candidates:
        if key != exclude:
            return (key, directive)
    return ("", "")


def shortlist_hotels(response: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The same bounded hotel list the ground-truth block renders — shared
    with the amenity-claim verifier (S07, amenity_guard.py) so it checks the
    synthesis text against EXACTLY the hotels the LLM was grounded in,
    whatever the response's source (search leaf, or an S07 inline tool
    shaped the same way: `{"results": [...]}`)."""
    results = (response or {}).get("results")
    return [h for h in (results or []) if isinstance(h, dict)][:MAX_HOTELS]


def shortlist_ground_truth_block(
    response: dict[str, Any] | None, profile: SessionProfile, language: str = "en"
) -> str:
    """System-prompt block anchoring the synthesis LLM to this turn's search
    outcome. Empty string when there is nothing to ground (no leaf results and
    no empty-search streak yet) — never adds an empty section to the prompt."""
    hotels = shortlist_hotels(response)
    date_block = date_context_block(response, language)
    if not hotels:
        if profile.consecutive_empty_searches > 0:
            # Date block LAST on this path: it is the authoritative cause and
            # must override the generic note's "widen the area / adjust the
            # budget" menu when the real reason is a closed same-day window.
            return "\n\n## CURRENT RESULTS (GROUND TRUTH)\n" + _EMPTY_SCREEN_NOTE + date_block
        return ""
    lines = [_hotel_line(hotel, profile.requested_window) for hotel in hotels]
    window_note = (
        "TIME WINDOWS: minute coverage is calculated from a single listed offer. "
        "A covered window does not require arriving earlier or leaving later: "
        "10:00–18:00 covers a requested stay of 10:30–17:00. Do not ask the user "
        "to accept different hours when coverage is confirmed. Not covered means "
        "the listed slots do not contain the full exact request, even if the site's "
        "rounded-hour search accepted them. Unknown proves no coverage. Never "
        "combine separate offers into a longer stay or infer extension/refund terms.\n"
        if any("minute coverage" in line for line in lines) else ""
    )
    return (
        "\n\n## CURRENT SHORTLIST (GROUND TRUTH)\n"
        + date_block + _HEADER + window_note + "\n".join(lines)
    )
