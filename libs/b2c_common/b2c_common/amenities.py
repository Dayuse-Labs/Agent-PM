"""Validated amenity changes shared by concierge and stateless search leaf."""
from __future__ import annotations

from typing import Any

AMENITY_KEYS = (
    "pool", "spa", "gym", "jacuzzi", "sauna", "restaurant", "breakfast",
    "pet_friendly", "shuttle",
    "bathtub", "shower", "air_conditioning", "room_service", "elevator",
    "rooftop_bar",
)


def grounded_amenity_update(value: Any, message: str) -> dict[str, Any] | None:
    """Validate the semantic extraction, without parsing customer prose.

    The literal quotation proves provenance only, not semantic correctness.
    Unknown operations or absent evidence cannot erase existing filters.
    An unsupported key must not discard a separately supported requirement.
    """
    if not isinstance(value, dict) or set(value) - {"add", "remove", "evidence"}:
        return None
    evidence = value.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip() or evidence not in message:
        return None
    result: dict[str, Any] = {"evidence": evidence}
    for key in ("add", "remove"):
        items = value.get(key, [])
        if not isinstance(items, list) or any(
            not isinstance(item, str) for item in items
        ):
            return None
        result[key] = list(dict.fromkeys(item for item in items if item in AMENITY_KEYS))
    if not result["add"] and not result["remove"]:
        return None
    # An internally contradictory extraction must not silently choose a side.
    if set(result["add"]) & set(result["remove"]):
        return None
    return result


def apply_amenity_update(current: list[str], update: dict[str, Any]) -> list[str]:
    """Apply only validated additions/removals; keep unrelated stored criteria."""
    kept = [key for key in current if key not in update["remove"]]
    return list(dict.fromkeys(kept + update["add"]))
