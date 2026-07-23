"""Inventory-density signal for the geo resolver (S-G3, arbitration A1-a).

"Does Dayuse have bookable hotels near this candidate?" is the single strongest
signal for disambiguating a geocoding homonym (Lisbon-PT vs Lisbon-Arkansas,
Victoria-BC vs the Seychelles) — travel players rank destinations against their
OWN supply, not raw prominence (geo memo §B: Airbnb/Expedia). We answer it from
a static coordinate snapshot compiled by `scripts/build_inventory_snapshot.py`,
counting hotels within a radius of the candidate centroid.

Radius (not the candidate's Mapbox bbox) is the unit on purpose: it mirrors how
`search_offers` actually finds hotels (a `lat`/`lon` + `radiusKm` query — probed
live 2026-07-23), and a region/district bbox would be so large it would count a
whole country's hotels and wrongly boost a coarse candidate. The bbox is kept on
the parsed candidate for the clarify label, not for counting.

The provider is an injectable `Protocol` (A1-a is the v1 implementation; a live
MCP `count_hotels_near` would be A1-c — same interface, no resolver change).
"""
from __future__ import annotations

import json
import math
import os
from typing import Protocol, runtime_checkable

# City-scale radius: a destination search anchors on a city/zone centroid and
# returns hotels across that metro — the density proxy must span the same area,
# not a single postcode. Tunable; the ranker only ever compares 0 vs >0 hard and
# uses the magnitude as a bounded soft weight, so the exact value is not delicate.
DEFAULT_RADIUS_KM = 25.0

_EARTH_RADIUS_KM = 6371.0088

_SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), "data", "inventory_snapshot.json")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two lat/lon points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


@runtime_checkable
class InventoryProvider(Protocol):
    """Counts bookable Dayuse hotels near a coordinate. Swappable: the static
    snapshot today (A1-a), a live MCP counter later (A1-c) — same signature."""

    def count_near(self, lat: float, lon: float, *, radius_km: float = DEFAULT_RADIUS_KM) -> int:
        ...


class SnapshotInventory:
    """`InventoryProvider` backed by the compiled coordinate snapshot."""

    def __init__(self, points: list[tuple[float, float]]):
        # Stored as parallel arrays so the hot loop avoids per-point tuple unpacking.
        self._lats = [p[0] for p in points]
        self._lons = [p[1] for p in points]

    @classmethod
    def from_file(cls, path: str = _SNAPSHOT_PATH) -> "SnapshotInventory":
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        pts = [(float(lat), float(lon)) for lat, lon in data.get("points", [])]
        return cls(pts)

    def count_near(self, lat: float, lon: float, *, radius_km: float = DEFAULT_RADIUS_KM) -> int:
        # Cheap equirectangular bounding-box pre-filter before the (costlier)
        # haversine — 8.7k points × ≤10 candidates per geocode stays well under 1 ms.
        dlat = radius_km / 111.0
        cos_lat = max(math.cos(math.radians(lat)), 0.01)
        dlon = radius_km / (111.0 * cos_lat)
        lo_lat, hi_lat = lat - dlat, lat + dlat
        lo_lon, hi_lon = lon - dlon, lon + dlon
        count = 0
        for plat, plon in zip(self._lats, self._lons):
            if plat < lo_lat or plat > hi_lat or plon < lo_lon or plon > hi_lon:
                continue
            if haversine_km(lat, lon, plat, plon) <= radius_km:
                count += 1
        return count


_default: SnapshotInventory | None = None


def get_inventory() -> SnapshotInventory:
    """Lazily-loaded process-wide snapshot provider (loaded once, never mutated)."""
    global _default
    if _default is None:
        _default = SnapshotInventory.from_file()
    return _default
