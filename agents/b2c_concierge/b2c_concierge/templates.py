"""Deterministic, code-owned turn answers of the b2c-concierge spine (zero LLM).

Every template exists in fr + en (triage's language). No template ever invents
a hotel, a price, a policy, or a link — honest-degradation posture: when a
capability is missing or a leaf is unreachable, SAY it and stop.
"""
from __future__ import annotations


def _pick(language: str, fr: str, en: str) -> str:
    return fr if language == "fr" else en


def ack_response(language: str) -> str:
    return _pick(
        language,
        "Bonjour ! Je suis le concierge Dayuse : dites-moi la ville (et la date si vous "
        "l'avez) et je vous trouve un hôtel en journée. Vous pouvez aussi me poser une "
        "question sur le fonctionnement de Dayuse.",
        "Hello! I'm the Dayuse concierge: tell me the city (and the date if you have one) "
        "and I'll find you a day-use hotel. You can also ask me how Dayuse works.",
    )


# --- S07: inline tools (real MCP wiring) — zero-LLM honest degradation ------

_INLINE_UNRESOLVED_FR = {
    "get_hotel_details": (
        "Je n'ai pas retrouvé cet hôtel — pouvez-vous me redonner son nom, ou "
        "me demander de chercher d'abord ?"
    ),
    "compare_hotels": (
        "Il me faut au moins deux hôtels à comparer — lesquels souhaitez-vous "
        "comparer ?"
    ),
    "generate_booking_link": (
        "Je n'arrive pas à préparer cette réservation pour le moment — pouvez-vous "
        "préciser l'hôtel, ou réessayer dans un instant ?"
    ),
}
_INLINE_UNRESOLVED_EN = {
    "get_hotel_details": (
        "I couldn't find that hotel — could you give me its name again, or ask "
        "me to search first?"
    ),
    "compare_hotels": "I need at least two hotels to compare — which ones would you like?",
    "generate_booking_link": (
        "I can't prepare that booking right now — could you specify the hotel, "
        "or try again in a moment?"
    ),
}


def inline_unresolved_response(target: str, language: str) -> str:
    """Honest degradation for an inline MCP tool call that could not resolve
    (hotel not found, fewer than 2 to compare, MCP unreachable, no bookable
    offer) — zero LLM, never invents a hotel/link that isn't there."""
    return _pick(language, _INLINE_UNRESOLVED_FR[target], _INLINE_UNRESOLVED_EN[target])


def _format_time_slot(start_time: str | None, end_time: str | None) -> str | None:
    """S-G6: `start_time`/`end_time` are already-formatted "HH:MM" strings
    (the offer's real minutes, e.g. offer.startMinute/endMinute) — no longer
    forces ":00" on every offer regardless of its actual minutes."""
    if not start_time or not end_time:
        return None
    return f"{start_time}–{end_time}"


def booking_offer_summary_response(
    *,
    hotel_name: str,
    date: str,
    start_time: str | None,
    end_time: str | None,
    price: str | None,
    language: str,
) -> str:
    """R9 (guard #12), step 1: presents the offer and asks for explicit
    confirmation — deterministic, zero LLM (a booking confirmation is
    security-sensitive: it must never depend on an LLM's phrasing)."""
    slot = _format_time_slot(start_time, end_time)
    if language == "fr":
        details = f"le {date}" + (f", créneau {slot}" if slot else "") + (f", {price}" if price else "")
        return (
            f"Voici l'offre pour {hotel_name} {details}. Confirmez-vous cette réservation ? "
            "Je ne génère le lien qu'après votre confirmation explicite."
        )
    details = f"on {date}" + (f", {slot} slot" if slot else "") + (f", {price}" if price else "")
    return (
        f"Here is the offer for {hotel_name} {details}. Do you confirm this booking? "
        "I'll only generate the link after your explicit confirmation."
    )


def booking_link_response(*, hotel_name: str, url: str | None, language: str) -> str:
    """R9 (guard #12), the authorized-link turn.

    S-CX5 considered dropping the URL from the text whenever a `booking_card`
    ships alongside it, and REVERTED that: the card rides an internal marker
    the facade turns into a payload key, so an A2A consumer (the eval harness,
    smoke_e2e) only ever sees this text — stripping the URL there made the
    answer useless off the widget path. It costs nothing to keep: the widget
    already removes raw URLs from the prose when a card is present
    (handlers/send.js), so the button is the only link the user sees."""
    if not url:
        return booking_needs_selection_response(None, None, language)
    if language == "fr":
        return f"C'est confirmé — voici votre lien de réservation pour {hotel_name} : {url}"
    return f"Confirmed — here is your booking link for {hotel_name}: {url}"


def booking_needs_selection_response(
    shortlist: list[dict] | None, reason: str | None, language: str
) -> str:
    """Booking couldn't resolve WHICH hotel — never dead-end. When a shortlist is
    on screen, LIST it so the user just picks; otherwise say what's missing,
    worded from the inline-tool reason (no hotel reference / hotel not found / no
    bookable offer). Zero LLM, never invents a hotel."""
    names = [str(h.get("name")) for h in (shortlist or []) if isinstance(h, dict) and h.get("name")]
    if names:
        listing = "\n".join(f"{i}. {name}" for i, name in enumerate(names, 1))
        return _pick(
            language,
            "Quel hôtel de cette liste souhaitez-vous réserver ? Dites-moi son nom :\n" + listing,
            "Which hotel from this list would you like to book? Tell me its name:\n" + listing,
        )
    if reason and "no bookable offer" in reason:
        return _pick(
            language,
            "Cet hôtel n'a pas d'offre en journée réservable pour cette date — "
            "voulez-vous essayer une autre date ou un autre hôtel ?",
            "That hotel has no bookable day-use offer for this date — want to try "
            "another date or another hotel?",
        )
    return _pick(
        language,
        "Je n'ai pas encore de liste d'hôtels à réserver — dites-moi d'abord la ville "
        "(et la date) et je cherche pour vous.",
        "I don't have a hotel list to book from yet — tell me the city (and date) "
        "first and I'll search for you.",
    )


_DEGRADED_FR = {
    "search": "Je n'arrive pas à joindre la recherche d'hôtels",
    "faq": "Je n'arrive pas à consulter les conditions Dayuse",
}
_DEGRADED_EN = {
    "search": "I can't reach the hotel search",
    "faq": "I can't look up the Dayuse conditions",
}


def search_exhausted_response(
    language: str, city: str | None = None, *, reason: str = "budget"
) -> str:
    """Terminal, zero-LLM message once the search is exhausted — reuses the
    SAME `profile.search_exhausted` flag/gate for two distinct triggers
    (extend, never a parallel mechanism):
    - "budget" (S12, audit 2026-07-20 — prod session 034c97c4, Rimini: an
      uncapped widen loop never told the user it had given up) — auto-widening
      was tried and still came back empty;
    - "pagination" (S-G5) — an "other options" request came back with zero
      NEW hotels: every match for the current filters has already been shown,
      so the message proposes relaxing ONE named constraint instead of the
      generic "try another city".
    Never a retry; the spine's pre-leaf gate only reaches here on a bare
    affirmative — a new constraint clears the flag and searches again instead.
    """
    where_fr = f" à {city}" if city else ""
    where_en = f" in {city}" if city else ""
    if reason == "pagination":
        return _pick(
            language,
            f"Vous avez vu tous les hôtels correspondant à vos critères{where_fr}. "
            "Voulez-vous que j'élargisse le budget, la zone, ou que je retire un filtre ?",
            f"You've now seen every hotel matching your criteria{where_en}. "
            "Want me to widen the budget, the area, or drop a filter?",
        )
    return _pick(
        language,
        f"Même après avoir élargi le budget, je ne trouve toujours rien{where_fr}. "
        "Essayez une autre ville, ou dites-moi ce que je peux ajuster (date, quartier).",
        f"Even after widening the budget, I still couldn't find anything{where_en}. "
        "Try a different city, or tell me what I should adjust (date, area).",
    )


def service_degraded_response(language: str) -> str:
    """Last-resort facade shield (S-CX1): an unexpected error escaped every
    inner degradation net, so the step that failed is unknown — generic
    honest wording, invents nothing, never a raw 500/dead stream."""
    return _pick(
        language,
        "Un souci technique m'empêche de répondre pour le moment, et je préfère "
        "ne rien inventer. Pouvez-vous réessayer dans un instant ?",
        "A technical issue is stopping me from answering right now, and I'd "
        "rather not make anything up. Could you try again in a moment?",
    )


def leaf_degraded_response(family: str, language: str, city: str | None = None) -> str:
    """Honest degradation when a leaf leg timed out or failed: say it — naming the
    destination when known so the user sees what was attempted — invent nothing,
    no retry (the 10 s budget is spent)."""
    where_fr = f" à {city}" if city and family == "search" else ""
    where_en = f" in {city}" if city and family == "search" else ""
    return _pick(
        language,
        f"{_DEGRADED_FR.get(family, _DEGRADED_FR['search'])}{where_fr} pour le moment, et je "
        "préfère ne rien inventer. Pouvez-vous réessayer dans un instant ?",
        f"{_DEGRADED_EN.get(family, _DEGRADED_EN['search'])}{where_en} right now, and I'd "
        "rather not make anything up. Could you try again in a moment?",
    )
