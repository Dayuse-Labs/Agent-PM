"""Offline tests of scripts/build_inventory_snapshot.py (S-G3, A1-a).

Pure functions only — no read of the real 29-market exports (CI has none). Locks
the coordinate-only extraction (no hotel attribute leaks), the deterministic,
stable output shape, and byte-for-byte reproducibility from the same input.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "build_inventory_snapshot.py"
_spec = importlib.util.spec_from_file_location("build_inventory_snapshot", _SCRIPT)
assert _spec is not None and _spec.loader is not None
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)


def _hotel(lat, lon, **extra):
    return {"latitude": lat, "longitude": lon, "name": "secret", "address": "secret", **extra}


def test_extract_points_keeps_only_valid_coordinates():
    records = [
        _hotel(48.8566, 2.3522),
        _hotel(None, 2.0),           # missing lat
        _hotel("x", "y"),            # garbage
        _hotel(0.0, 0.0),            # null-island → dropped
        _hotel(200.0, 2.0),          # out of range
        _hotel(40.0, -74.0),
    ]
    pts = builder.extract_points(records)
    assert pts == [[48.8566, 2.3522], [40.0, -74.0]]


def test_extract_points_carries_no_hotel_attributes():
    pts = builder.extract_points([_hotel(1.0, 2.0, price=999, stars=5)])
    assert pts == [[1.0, 2.0]]  # a coordinate, nothing else


def test_build_snapshot_shape_and_counts():
    markets = {"fr": [_hotel(48.85, 2.35), _hotel(43.6, 1.44)], "pt": [_hotel(38.72, -9.14)]}
    snap = builder.build_snapshot(markets, source_export_date="2026-07-15")
    assert snap["schema_version"] == builder.SCHEMA_VERSION
    assert snap["hotel_count"] == 3
    assert snap["markets"] == {"FR": 2, "PT": 1}
    assert snap["source_export_date"] == "2026-07-15"
    assert len(snap["points"]) == 3


def test_build_snapshot_points_are_sorted_for_stable_diffs():
    markets = {"fr": [_hotel(48.85, 2.35), _hotel(10.0, 10.0), _hotel(1.0, 1.0)]}
    snap = builder.build_snapshot(markets, source_export_date="2026-07-15")
    assert snap["points"] == sorted(snap["points"])


def test_build_snapshot_is_deterministic():
    markets = {"fr": [_hotel(48.85, 2.35)], "it": [_hotel(45.46, 9.19)]}
    a = builder.build_snapshot(markets, source_export_date="2026-07-15")
    b = builder.build_snapshot(markets, source_export_date="2026-07-15")
    assert a == b


def test_market_count_drops_records_without_coordinates():
    markets = {"xx": [_hotel(1.0, 2.0), _hotel(None, None)]}
    snap = builder.build_snapshot(markets, source_export_date="2026-07-15")
    assert snap["markets"]["XX"] == 1
    assert snap["hotel_count"] == 1
