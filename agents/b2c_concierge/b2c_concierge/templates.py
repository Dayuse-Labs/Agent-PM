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


_STUB_FR = {
    "get_hotel_details": "Je ne peux pas encore afficher la fiche détaillée d'un hôtel",
    "compare_hotels": "Je ne peux pas encore comparer des hôtels",
    "generate_booking_link": "Je ne peux pas encore générer de lien de réservation",
}
_STUB_EN = {
    "get_hotel_details": "I can't show a hotel's detailed sheet yet",
    "compare_hotels": "I can't compare hotels yet",
    "generate_booking_link": "I can't generate a booking link yet",
}


def stub_response(tool: str, language: str) -> str:
    """Honest answer for an inline capability not wired yet (S4+)."""
    return _pick(
        language,
        f"{_STUB_FR[tool]} — cette fonction arrive très bientôt. En attendant, je peux "
        "chercher un hôtel en journée ou répondre à vos questions sur Dayuse.",
        f"{_STUB_EN[tool]} — this feature is coming very soon. In the meantime I can "
        "search day-use hotels or answer your questions about Dayuse.",
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


def _format_time_slot(start_hour: int | None, end_hour: int | None) -> str | None:
    if start_hour is None or end_hour is None:
        return None
    return f"{start_hour:02d}:00–{end_hour:02d}:00"


def booking_offer_summary_response(
    *,
    hotel_name: str,
    date: str,
    start_hour: int | None,
    end_hour: int | None,
    price: str | None,
    language: str,
) -> str:
    """R9 (guard #12), step 1: presents the offer and asks for explicit
    confirmation — deterministic, zero LLM (a booking confirmation is
    security-sensitive: it must never depend on an LLM's phrasing)."""
    slot = _format_time_slot(start_hour, end_hour)
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
    """R9 (guard #12), step 2: the tracked link, only ever reached after an
    explicit confirmation turn set `pending_booking` and matched it."""
    if not url:
        return inline_unresolved_response("generate_booking_link", language)
    if language == "fr":
        return f"C'est confirmé — voici votre lien de réservation pour {hotel_name} : {url}"
    return f"Confirmed — here is your booking link for {hotel_name}: {url}"


_DEGRADED_FR = {
    "search": "Je n'arrive pas à joindre la recherche d'hôtels pour le moment",
    "faq": "Je n'arrive pas à consulter les conditions Dayuse pour le moment",
}
_DEGRADED_EN = {
    "search": "I can't reach the hotel search right now",
    "faq": "I can't look up the Dayuse conditions right now",
}


def leaf_degraded_response(family: str, language: str) -> str:
    """Honest degradation when a leaf leg timed out or failed: say it, invent
    nothing, no retry (the 10 s budget is spent)."""
    return _pick(
        language,
        f"{_DEGRADED_FR.get(family, _DEGRADED_FR['search'])} et je préfère ne rien "
        "inventer. Pouvez-vous réessayer dans un instant ?",
        f"{_DEGRADED_EN.get(family, _DEGRADED_EN['search'])} and I'd rather not make "
        "anything up. Could you try again in a moment?",
    )
