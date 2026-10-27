"""POST /v3/chat/welcome — the opening view of the mobile app (E, 2026-10-27).

The app opens the widget in a WebView with `window.__DAYUSE_NATIVE__`; the
widget then asks `/v3/chat/welcome` for a personalized greeting and opening
chips (`web/vendor/static/js/chat/index.js::startFromAppContext`). agent-usa
served it (`src/api/routes/chat.py::_handle_welcome`, contract
`docs/SPEC_WIDGET_NATIVE_CONTEXT.md`); since the switch of ai.dayuse.com to
AgentB2C (2026-10-26) the widget got a 404 and kept its default greeting.

Same contract, the minimum of it: `{is_personalized, message, suggestions,
market}`. Deterministic, no LLM, no session, no trace. Personalized only when
the app sent the user's past bookings with their cities — the chips name
those cities ("Day room in Lyon"), and a chip is sent as the user's message
when tapped, so each one is a plain search request. Anything else answers
`is_personalized: false`, and the widget keeps its own greeting and chips.

GDPR: `lastBookings` (hotel names, prices, cities) is read in memory only —
never logged, never stored, never sent to an LLM or to Langfuse; the metric
line carries counts. Prices and hotel names are not even read.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

#: The app sends ~3 bookings; a bound on what is read whatever it sends.
_MAX_BOOKINGS = 5
_MAX_CHIPS = 2
_MAX_CITY_LEN = 80

_STRINGS: dict[str, dict[str, str]] = {
    "en": {"chip": "Day room in {city}",
           "welcome": "Welcome back 👋 A day room in {city} again — or somewhere new?"},
    "fr": {"chip": "Chambre en journée à {city}",
           "welcome": "Re-bonjour 👋 Une chambre en journée à {city}, ou ailleurs ?"},
    "es": {"chip": "Habitación de día en {city}",
           "welcome": "¡Hola de nuevo! 👋 ¿Una habitación de día en {city} u otro lugar?"},
    "it": {"chip": "Camera a uso diurno a {city}",
           "welcome": "Bentornato! 👋 Una camera a uso diurno a {city} o altrove?"},
    "de": {"chip": "Tageszimmer in {city}",
           "welcome": "Willkommen zurück! 👋 Ein Tageszimmer in {city} oder woanders?"},
    "pt": {"chip": "Quarto de dia em {city}",
           "welcome": "Bem-vindo de volta! 👋 Um quarto de dia em {city} ou noutro sítio?"},
    "nl": {"chip": "Dagkamer in {city}",
           "welcome": "Welkom terug! 👋 Een dagkamer in {city} of ergens anders?"},
}


def booking_cities(native_context: Any) -> list[str]:
    """The cities of the user's past bookings, most booked first (ties keep
    the app's order), each once, case aside. Accepts the app's camelCase and
    agent-usa's snake_case; anything malformed is skipped, never raised."""
    if not isinstance(native_context, dict):
        return []
    bookings = native_context.get("lastBookings") or native_context.get("last_bookings")
    if not isinstance(bookings, list):
        return []
    cities: list[str] = []
    for booking in bookings[:_MAX_BOOKINGS]:
        if not isinstance(booking, dict):
            continue
        city = booking.get("hotelCity") or booking.get("hotel_city")
        if isinstance(city, str) and city.strip() and len(city.strip()) <= _MAX_CITY_LEN:
            cities.append(" ".join(city.split()))
    counts = Counter(c.casefold() for c in cities)
    first_spelling: dict[str, str] = {}
    for city in cities:
        first_spelling.setdefault(city.casefold(), city)
    order = {key: i for i, key in enumerate(first_spelling)}
    ranked = sorted(first_spelling, key=lambda key: (-counts[key], order[key]))
    return [first_spelling[key] for key in ranked]


def welcome_payload(native_context: Any, language: str, currency: str | None) -> dict[str, Any]:
    """The `/v3/chat/welcome` body for this app user, in `language` (one of
    the 7 the concierge answers in; anything else reads English)."""
    strings = _STRINGS.get(language, _STRINGS["en"])
    market = {"language": language if language in _STRINGS else "en", "currency": currency}
    cities = booking_cities(native_context)
    if not cities:
        return {"is_personalized": False, "message": "", "suggestions": [], "market": market}
    return {
        "is_personalized": True,
        "message": strings["welcome"].format(city=cities[0]),
        "suggestions": [strings["chip"].format(city=city) for city in cities[:_MAX_CHIPS]],
        "market": market,
    }
