"""Leaf → concierge wire-seam lock (S-G10, fixes S-G9 finding 1).

The 07/23 gate re-run showed `distance_origin` computed correctly by the leaf
but NEVER reaching the profile: `emit_search_datapart` attached it as a
top-level sibling of `profile_delta`, while the concierge only ever reads
`profile_delta` off the wire. Each side's own unit tests passed around the bug
(the leaf test asserted the buggy top-level placement; the concierge tests
constructed `SessionProfile(distance_origin=...)` directly). This test walks
the actual seam: leaf emit → decoded DataPart → `apply_profile_delta` →
`build_active_filters`, so a placement regression on either side fails here.
"""
from __future__ import annotations

from b2c_concierge.facade import build_active_filters, normalize_hotels
from b2c_concierge.profile import SessionProfile, apply_profile_delta
from hotel_search_agent.response_bridge import (
    decode_datapart,
    emit_search_datapart,
    normalize_hotel,
)

_RESULTS_KEY = "temp:hotel_search_results"
_DISTANCE_ORIGIN_KEY = "temp:hotel_search_distance_origin"


class _Ctx:
    def __init__(self, state):
        self.state = state


def test_distance_origin_travels_from_leaf_emit_to_active_filters():
    origin = {"latitude": 48.8566, "longitude": 2.3522, "label": "Paris", "type": "city_centroid"}
    content = emit_search_datapart(
        _Ctx({
            _RESULTS_KEY: [{"id": 1, "name": "Villa", "latitude": 48.8, "longitude": 2.3, "distance_km": 0.5}],
            _DISTANCE_ORIGIN_KEY: origin,
        })
    )
    payload = next(d for d in (decode_datapart(p) for p in content.parts) if d is not None)

    profile = SessionProfile()
    apply_profile_delta(profile, payload.get("profile_delta") or {}, "hotel in Paris")

    assert profile.distance_origin == origin
    assert build_active_filters(profile)["distance_origin"] == origin


def test_numeric_price_and_review_count_survive_the_whole_card_path():
    """S-CX3a: a numeric price is worthless if any hop drops or mangles it —
    walk the REAL card path (leaf normalize → emit → JSON DataPart → decode →
    facade payload mapping), the same class of seam that swallowed
    `distance_origin` above. The JSON round-trip is part of the point: the
    price must arrive as a plain int, not a float that prints as 5432.0."""
    card = normalize_hotel(
        {
            "hotelId": 22293,
            "name": "Villa Paris Orly",
            "globalAverageRating": 4.64,
            "totalReview": 412,
            "offers": [
                {"priceEuro": 5432, "startHour": 10, "startMinute": 0, "endHour": 17, "endMinute": 0}
            ],
        }
    )
    content = emit_search_datapart(_Ctx({_RESULTS_KEY: [card]}))
    payload = next(d for d in (decode_datapart(p) for p in content.parts) if d is not None)

    out = normalize_hotels(payload["results"])[0]
    assert out["price"] == "€54.32"  # the display string still ships
    assert out["price_eur_cents"] == 5432 and isinstance(out["price_eur_cents"], int)
    assert out["rating_count"] == 412
