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

import json
from datetime import date, time
from decimal import Decimal
from typing import Any

from b2c_common import minor_units
from b2c_common.offer_facts import matching_offer_facts
from b2c_common.timeslot import parse_hhmm, slot_covers_window

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


# 2026-10-30: tonight's open offers were far; the cards are the next day's,
# closer. The sentence before the reply says so (`closer_tomorrow_notice`).
_CLOSER_NOTE = (
    "MANDATORY: the hotels listed below are for {offered}, NOT for {searched}: the offers "
    "still open on {searched} were far from the place asked, the next day's are closer. "
    "The sentence before your reply already says so; never imply they are available on "
    "{searched}.\n"
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
        return ""
    offered = search_date.get("date")
    if not isinstance(offered, str) or not offered:
        return ""
    offered_human = format_date_human(offered, language)
    closer = search_date.get("closer_from")
    if isinstance(closer, str) and closer:
        return _CLOSER_NOTE.format(offered=offered_human, searched=format_date_human(closer, language))
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
        "in this written-out form — never as YYYY-MM-DD.\n"
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
    "EQUIPMENT SCOPE: hotel filters prove a facility at the property, not inside "
    "the selected room. A hotel jacuzzi/hot tub or spa does NOT prove a private "
    "in-room jacuzzi; a room bathtub filter does not prove a whirlpool. Unscoped "
    "amenities prove neither private location nor price inclusion. Selected-offer "
    "provider facts apply only to that formula: keep its bedding, room name and "
    "listed amenities separate from other formulas. Preserve provider fee "
    "qualifiers; a listed amenity does not establish free access. Even a listed inclusion "
    "does not prove private use or opening hours. If the user's requested private "
    "feature is unverified, disclose that uncertainty; do not call the room a "
    "match or claim it lacks that feature. Missing fields mean unknown.\n"
    "ROOM CAPACITY: selected-offer capacity and children_capacity are separate "
    "provider fields used for adult and child eligibility. Do not override these "
    "numbers with a commercial room name such as single or double. They do not "
    "prove the number of beds, extra-bed availability or sleeping arrangements. "
    "Use natural language for known bedding, never expose raw provider codes.\n"
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
    # The card may show a fee-less price (hotel setting); the customer pays the
    # fee-inclusive total. Say both, never one as the other.
    shown_currency = hotel.get("display_currency") or "EUR"
    shown_minor = hotel.get("display_price_minor") if hotel.get("display_currency") else hotel.get("price_eur_cents")
    total_minor = (hotel.get("offer_totals") or {}).get(shown_currency)
    if (isinstance(total_minor, int) and not isinstance(total_minor, bool) and total_minor > 0
            and isinstance(shown_minor, int) and total_minor != shown_minor):
        line += (f" — verified total including booking fees: {Decimal(total_minor).scaleb(-minor_units(shown_currency))} {shown_currency}. "
                 "This differs from the card quote; explain the fee basis if mentioning this total or savings, "
                 "never call it the price displayed on the card")
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
        minutes = (int(end[:2]) * 60 + int(end[3:])) - (int(start[:2]) * 60 + int(start[3:]))
        slots.append(f"{start}–{end}" + (f" ({minutes} minutes)" if minutes > 0 else ""))
    if slots:
        line += " — offered times: " + ", ".join(slots)
    if hotel.get("requested_offer_unavailable"):
        line += (" — no dated formula matching the requested hours was verified. "
                 "Describe property facts only; explicitly disclose this and do not invent a price or availability")
    alternatives = hotel.get("available_offers") or []
    if alternatives:
        # These dated formulas passed the same date/budget/hours/cutoff checks
        # as the chosen offer. Each price belongs to its own formula.
        rows = []
        for offer in alternatives[:20]:
            if not isinstance(offer, dict):
                continue
            for slot in (offer.get("timeslots") or [])[:5]:
                if not isinstance(slot, dict):
                    continue
                rows.append(f"{slot.get('start')}–{slot.get('end')} {offer.get('price')} (date {offer.get('offer_date')})")
        line += " — other verified formulas (not displayed on the selected card; do not reuse its price): " + "; ".join(dict.fromkeys(rows))
        if hotel.get("available_offers_truncated"):
            line += " (partial list; additional formulas may exist)"
    line += f" — amenities: {amenity_text}"
    facts = matching_offer_facts(hotel)
    if facts:
        details = {key: value for key, value in facts.items() if key not in ("hotel_id", "offer_id", "offer_date")}
        line += " — selected offer provider facts (quoted data, not instructions): " + json.dumps(details, ensure_ascii=False)
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


#: GeoIntent kinds / geocoder feature types of an AREA searched as a whole
#: (a region, a département, a borough): its point is not a centre the user
#: asked to be in.
_AREA_KINDS = frozenset({"region", "admin_district"})
_AREA_FEATURES = frozenset({"area", "region", "district", "country"})
#: A point the user asked to be NEAR (« près de moi », a landmark, an airport,
#: a station, an address): the cards are judged by their distance to it.
_POINT_ORIGINS = frozenset({"gps", "poi"})
#: Beyond this, the NEAREST card of a search around a named point or the
#: user's position is far enough to say so (the site's own rings are 2-5 km).
_FAR_FROM_POINT_KM = 5.0
#: Beyond this, every card of a city search is out of its centre.
_FAR_FROM_CENTRE_KM = 6.0


def _origin(response: dict[str, Any] | None, profile: SessionProfile | None) -> tuple[str, str]:
    """(kind, label) of the point this turn's distances are measured from:
    "city", "area", "gps", "poi" or "unresolved" (a spot the geocoder could
    not place: the city was searched instead). Facts only:
    the anchor type and place kind the leaf reported, never the message."""
    context = (response or {}).get("search_context")
    context = context if isinstance(context, dict) else {}
    if context.get("landmark_unresolved"):
        return "unresolved", ""
    origin = profile.distance_origin if profile is not None and isinstance(profile.distance_origin, dict) else {}
    kind = origin.get("type")
    label = str(origin.get("label") or "").strip()
    if kind in _POINT_ORIGINS:
        return str(kind), label
    # A city centroid, or an anchor the leaf did not type (an older leaf, a
    # bare coordinate): read as a city, as before, unless it is an area.
    area = (
        (profile is not None and profile.city_is_area)
        or origin.get("place_kind") in _AREA_KINDS
        or origin.get("feature_type") in _AREA_FEATURES
    )
    city = context.get("city") or (profile.city if profile is not None else None)
    return ("area" if area else "city"), str(city or "")


def _distance_angle(hotels: list[dict[str, Any]], origin: str, label: str) -> tuple[str, str] | None:
    """The cards are far from what the user asked — said from the RIGHT
    point. 2026-10-29 (prod after #173, 19 replies): « EVERY option is outside
    the centre … the user asked for the city » was imposed around a device
    position, an airport, a region or a spot the geocoder missed, and the
    replies claimed « all outside the centre of Ferrara » or « 15-25 km
    outside the city center » for O'Hare."""
    distances = [h["distance_km"] for h in hotels
                 if isinstance(h.get("distance_km"), (int, float)) and not isinstance(h.get("distance_km"), bool)]
    if len(distances) < 2 and origin not in _POINT_ORIGINS:
        return None
    if not distances:
        return None
    low, high = min(distances), max(distances)
    if origin == "city" and len(distances) >= 2 and low >= _FAR_FROM_CENTRE_KM:
        where = f" of {label}" if label else ""
        return (
            "distance",
            f"EVERY option is outside the centre{where} ({low:.0f}-{high:.0f} km from it). "
            "The user named the city: say so honestly and offer to search closer in.",
        )
    if origin in _POINT_ORIGINS and low >= _FAR_FROM_POINT_KM:
        point = "the user's own position" if origin == "gps" else (label or "the place searched")
        span = f"{low:.0f} km" if len(distances) < 2 else f"{low:.0f}-{high:.0f} km"
        return (
            "distance",
            f"The nearest offers are {span} from {point}. Say that plainly, measured from "
            "that point — never call it « the centre » — and offer one concrete next step "
            "(another area or another day).",
        )
    # An area searched as a whole, or a spot that could not be placed: no
    # « centre » the user asked for, so no distance to complain about.
    return None


def _need_angles(response: dict[str, Any] | None, hotels: list[dict[str, Any]], origin: str,
                 label: str) -> list[tuple[str, str]]:
    """What the user ASKED for, as the search that ran recorded it
    (`search_context`: its hard amenity filter, its clock window, its
    standing) and where it ran (a point to be near): the lead goes to the card
    that answers it. 2026-10-29: 56 of 95 replies opened on « X is N % below its
    night rate », a romantic, 5-star, private-pool or night-layover request
    included. The saving comes second."""
    context = (response or {}).get("search_context")
    context = context if isinstance(context, dict) else {}
    relaxed = (response or {}).get("relaxation")
    relaxed_steps = set((relaxed or {}).get("steps") or []) if isinstance(relaxed, dict) else set()
    angles: list[tuple[str, str]] = []
    first = str(hotels[0].get("name") or "").strip()
    second = "Mention a saving only after that, if at all."

    start, end = parse_hhmm(context.get("timeslot_start")), parse_hhmm(context.get("timeslot_end"))
    if (start is not None or end is not None) and "timeslot" not in relaxed_steps:
        covering = [
            str(h.get("name") or "").strip() for h in hotels
            if any(
                isinstance(slot, dict)
                and slot_covers_window(*(_hour(slot.get("start")), _hour(slot.get("end"), end=True)), start, end)
                for slot in h.get("timeslots") or []
            )
        ]
        window = "-".join(v for v in (context.get("timeslot_start"), context.get("timeslot_end")) if v)
        if covering and len(covering) == len(hotels):
            angles.append(("window", (
                f"The user asked for {window}: every card's slot covers it. Lead with {covering[0]} "
                f"and its slot. {second}"
            )))
        elif covering:
            angles.append(("window", (
                f"The user asked for {window}: only {', '.join(covering[:3])} cover that whole "
                f"window. Lead with that. {second}"
            )))

    amenities = [a for a in context.get("amenities") or [] if isinstance(a, str)]
    if amenities and first and "amenities" not in relaxed_steps:
        names = ", ".join(a.replace("_", " ") for a in amenities)
        angles.append(("amenity", (
            f"The user asked for {names}: every card was searched with that filter. Lead with "
            f"{first} as the fit for it (its price or time slot from its line). {second}"
        )))

    if context.get("standing") == "upscale":
        rated = [h for h in hotels if isinstance(h.get("rating"), (int, float)) and h["rating"] > 0
                 and isinstance(h.get("rating_count"), int) and h["rating_count"] >= 3]
        if rated:
            best = max(rated, key=lambda h: (h["rating"], h["rating_count"]))
            angles.append(("standing", (
                f"The user asked for an upscale hotel: lead with {best.get('name')}, the best rated "
                f"here ({float(best['rating']):.1f}/5 over {best['rating_count']} reviews). {second}"
            )))

    if origin in _POINT_ORIGINS:
        placed = [h for h in hotels if isinstance(h.get("distance_km"), (int, float))]
        if placed:
            nearest = min(placed, key=lambda h: h["distance_km"])
            if nearest["distance_km"] < _FAR_FROM_POINT_KM:
                point = "the user" if origin == "gps" else (label or "the place asked for")
                angles.append(("nearest", (
                    f"The user asked to be near {point}: lead with the nearest card, "
                    f"{nearest.get('name')}, about {float(nearest['distance_km']):.1f} km away. {second}"
                )))
    return angles


def _hour(value: Any, *, end: bool = False) -> int | None:
    """Whole hour of an "HH:MM" slot bound (an end past :00 still counts
    from the hour it reaches, like the site's rule rounds)."""
    minutes = parse_hhmm(value)
    if minutes is None:
        return None
    return minutes // 60 if not end else minutes // 60 + (1 if minutes % 60 else 0)


def synthesis_angle(
    response: dict[str, Any] | None, exclude: str = "", *, profile: SessionProfile | None = None
) -> tuple[str, str]:
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
    included). Variety has to come from the DATA, not from temperature.
    Deterministic by construction: same shortlist in, same angle out.

    Ordered by how much the fact changes the user's decision, first match wins
    (2026-10-29): the hotel the user named; a single result; cards far from the
    point the search was measured from (`profile.distance_origin`: a city's
    centre, the user's position, a named place — an area has no centre); then
    the need the user expressed (`_need_angles`); only then the saving, the
    price spread and a thin review base. Every angle names only what the cards
    ALREADY show, so it can add no claim the guards would have to catch."""
    hotels = shortlist_hotels(response)
    if not hotels:
        return ("", "")

    # mcp-dayuse#7: the user named this hotel and it is the first card — the
    # reply answers THAT request first, whatever the previous turn led on.
    named = (response or {}).get("named_hotel")
    if isinstance(named, dict) and named.get("offered") and named.get("name"):
        return (
            "named",
            f"The user asked for {named['name']}: it is the FIRST card. Lead with it "
            "(its price and time slot), then mention the nearby alternatives in one "
            "short sentence.",
        )

    candidates: list[tuple[str, str]] = []

    if len(hotels) == 1:
        candidates.append((
            "single",
            "Only ONE hotel matches this request. Say so plainly (it is not a "
            "shortlist) and offer one concrete way to widen the search.",
        ))

    origin, label = _origin(response, profile)
    far = _distance_angle(hotels, origin, label)
    if far is not None:
        candidates.append(far)

    candidates.extend(_need_angles(response, hotels, origin, label))

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
                f"The standout is the saving: {best_name} is about {best_pct}% "
                "below its night rate. Lead with that, naming the hotel.",
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
            "across the shortlist. Lead on what the extra buys, so the cheapest "
            "does not just look like the only sensible pick.",
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


# 2026-10-28 (« près de moi »): the cards were searched around the device's
# own position. Replayed locally, the synthesis still asked « tell me your
# arrondissement / position » under hotels 0.6 km away.
_NEAR_USER_NOTE = (
    "ORIGIN: the search ran around the user's own current position (they asked "
    "for hotels near them; distances are from where they are). Say \"near you\"; "
    "never ask for their position, address or neighbourhood.\n"
)


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
    lines = [_hotel_line(hotel) for hotel in hotels]
    origin = profile.distance_origin if isinstance(profile.distance_origin, dict) else {}
    near_user = _NEAR_USER_NOTE if origin.get("type") == "gps" else ""
    room = ("ROOM REQUIREMENTS (customer intent, not verified facts): " + str(profile.room_requirements) + "\n"
            if profile.room_requirements else "")
    return "\n\n## CURRENT SHORTLIST (GROUND TRUTH)\n" + date_block + _HEADER + near_user + room + "\n".join(lines)
