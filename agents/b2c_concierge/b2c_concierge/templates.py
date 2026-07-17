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
