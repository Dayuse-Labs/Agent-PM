"""Validated semantic location edits; no text matching or geographic catalogue.

These are requested locations, never verified coordinates. Only the geocoder
can promote them to a resolved location. Missing fields mean carry over on a
refinement, and clear on replacement; an explicit null clears a field.
"""
from typing import Any

LOCATION_FIELDS = ("city", "zone", "metro", "country_code", "region", "kind")


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
    if result.get("kind") not in (None, "city", "area", "landmark", "unknown"):
        return None
    if country is not None:
        if len(country) != 2 or not country.isascii() or not country.isalpha():
            return None
        result["country_code"] = country.upper()
    if result["action"] == "retain":
        return {"action": "retain"} if len(result) == 1 else None
    if result["action"] == "replace" and not any(result.get(k) for k in ("city", "zone", "metro")):
        return None
    if result.get("city") and isinstance(result.get("zone"), str) and (
        result["zone"].casefold() == result["city"].casefold()
        or result["zone"].partition(",")[0].strip().casefold() == result["city"].casefold()
    ):
        # A city-level request must not turn a repeated "city, state" label
        # into a POI search. On a clarification, keep the earlier area intact.
        if result["action"] == "replace":
            result["zone"] = None
        else:
            result.pop("zone", None)
    if result.get("kind") == "city" and result.get("zone"):
        result["kind"] = "area"
    return result


def location_request(previous: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    """Apply a validated edit without borrowing stale country/area on a move."""
    result = {} if update["action"] == "replace" else {
        key: previous[key] for key in LOCATION_FIELDS if key in previous
    }
    result.update({key: update[key] for key in LOCATION_FIELDS if key in update})
    if update["action"] == "refine" and update.get("kind") == "city" and previous.get("zone"):
        result["kind"] = previous.get("kind")
    return {key: result.get(key) for key in LOCATION_FIELDS}
