"""A fuzzy catalog suggestion is not evidence of the customer's hotel identity."""
from __future__ import annotations

import unicodedata
from typing import Any


def _tokens(value: Any) -> set[str]:
    if not isinstance(value, str):
        return set()
    folded = unicodedata.normalize("NFKD", value.casefold())
    return set("".join(
        ch if ch.isalnum() else " "
        for ch in folded if not unicodedata.combining(ch)
    ).split())


def named_identity_grounded(query: Any, hotel: dict[str, Any]) -> bool:
    """Require the requested words in the catalog name and optional city.

    No fuzzy distance threshold, alias list or new model call can promote a
    provider suggestion to user intent. Typos that do not satisfy this check
    need an explicit full name; this deliberately trades some recall for an
    honest clarification. A city alone is never a property name.
    """
    requested = _tokens(query)
    name = _tokens(hotel.get("name"))
    city = _tokens(hotel.get("cityName") or hotel.get("city"))
    return bool(requested and requested & (name - city) and requested <= name | city)
