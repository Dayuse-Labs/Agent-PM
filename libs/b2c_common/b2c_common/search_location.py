"""Validated semantic location edits; no text matching or geographic catalogue.

These are requested locations, never verified coordinates. Only the geocoder
can promote them to a resolved location. Missing fields mean carry over on a
refinement, and clear on replacement; an explicit null clears a field.
"""
from typing import Any

LOCATION_FIELDS = ("city", "zone", "metro", "country_code", "region")


def parse_location_update(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or value.get("action") not in {"retain", "replace", "refine"}:
        return None
    if set(value) - {"action", *LOCATION_FIELDS}:
        return None
    result: dict[str, Any] = {"action": value["action"]}
    for key in LOCATION_FIELDS:
        if key not in value:
            continue
        item = value[key]
        if item is not None and (not isinstance(item, str) or not item.strip() or len(item) > 160):
            return None
        result[key] = item.strip() if isinstance(item, str) else None
    country = result.get("country_code")
    if country is not None:
        if len(country) != 2 or not country.isascii() or not country.isalpha():
            return None
        result["country_code"] = country.upper()
    if result["action"] == "retain":
        return {"action": "retain"} if len(result) == 1 else None
    if result["action"] == "replace" and not any(result.get(k) for k in ("city", "zone", "metro")):
        return None
    return result


def location_request(previous: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Apply a validated edit without borrowing stale country/area on a move."""
    result = {} if update["action"] == "replace" else {
        key: previous[key] for key in LOCATION_FIELDS if key in previous
    }
    result.update({key: update[key] for key in LOCATION_FIELDS if key in update})
    return {key: result.get(key) for key in LOCATION_FIELDS}
