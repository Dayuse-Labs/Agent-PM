"""Provider-owned location snapshot, bound to the exact requested geography.

The concierge alone persists this payload. A stateless leaf may reuse it on a
preserving turn; a new request must obtain a fresh provider resolution.
"""
from __future__ import annotations

import math
from typing import Any

from .search_location import LOCATION_FIELDS


def request_identity(request: dict) -> dict:
    return {k: str(request.get(k) or "").strip().casefold() for k in LOCATION_FIELDS}


def verified_resolution(snapshot: Any, request: dict) -> dict | None:
    if not isinstance(snapshot, dict) or snapshot.get("request") != request_identity(request):
        return None
    result = snapshot.get("resolution")
    if not isinstance(result, dict) or result.get("ok") is not True:
        return None
    if not isinstance(result.get("provider_place_id"), str) or not result["provider_place_id"]:
        return None
    country = result.get("country_code")
    if not isinstance(country, str) or len(country) != 2 or not country.isascii() or not country.isalpha():
        return None
    for key, limit in (("latitude", 90), ("longitude", 180)):
        value = result.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > limit:
            return None
    return dict(result)


def location_snapshot(request: dict, result: dict) -> dict | None:
    payload = {k: result.get(k) for k in (
        "ok", "provider_place_id", "latitude", "longitude", "resolved_place",
        "resolved_feature_type", "distance_origin_type", "country_code", "profile_delta",
    )}
    snapshot = {"request": request_identity(request), "resolution": payload}
    return snapshot if verified_resolution(snapshot, request) else None
