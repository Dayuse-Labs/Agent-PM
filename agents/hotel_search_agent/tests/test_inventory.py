"""SnapshotInventory — radius-based density counting (S-G3, A1-a)."""
from __future__ import annotations

from hotel_search_agent.inventory import (
    DEFAULT_RADIUS_KM,
    SnapshotInventory,
    get_inventory,
    haversine_km,
)


def test_haversine_known_distance_paris_to_london():
    # Paris (48.8566, 2.3522) → London (51.5074, -0.1278) ≈ 344 km.
    d = haversine_km(48.8566, 2.3522, 51.5074, -0.1278)
    assert 330 < d < 360


def test_count_near_counts_points_within_radius():
    # Three points clustered near Paris, one far away in New York.
    pts = [(48.85, 2.35), (48.86, 2.36), (48.90, 2.40), (40.71, -74.0)]
    inv = SnapshotInventory(pts)
    assert inv.count_near(48.855, 2.355, radius_km=10.0) == 3
    assert inv.count_near(40.71, -74.0, radius_km=10.0) == 1


def test_count_near_zero_for_empty_region():
    inv = SnapshotInventory([(48.85, 2.35)])
    # Middle of the Atlantic — nothing within 25 km.
    assert inv.count_near(30.0, -40.0, radius_km=DEFAULT_RADIUS_KM) == 0


def test_radius_boundary_is_inclusive_ish_and_excludes_beyond():
    inv = SnapshotInventory([(0.0, 0.0), (0.0, 1.0)])  # ~111 km apart at the equator
    assert inv.count_near(0.0, 0.0, radius_km=50.0) == 1   # only the point itself
    assert inv.count_near(0.0, 0.0, radius_km=150.0) == 2  # both


def test_from_file_loads_the_shipped_snapshot():
    inv = get_inventory()
    # Paris has plenty of Dayuse hotels; the middle of the Pacific has none.
    assert inv.count_near(48.8566, 2.3522, radius_km=DEFAULT_RADIUS_KM) > 0
    assert inv.count_near(0.0, -160.0, radius_km=DEFAULT_RADIUS_KM) == 0


def test_get_inventory_is_cached_singleton():
    assert get_inventory() is get_inventory()


def test_shipped_snapshot_has_the_expected_market_scale():
    # 8 701 hotels across 29 markets (matches the eval fixture manifest).
    inv = SnapshotInventory.from_file()
    assert len(inv._lats) == 8701
