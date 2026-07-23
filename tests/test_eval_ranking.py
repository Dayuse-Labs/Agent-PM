"""Offline tests for scripts/eval_ranking.py (S-G9, A8-a ranking eval design).

All pure functions (no network, no MCP session, no live services):
`_haversine_km`, `_hour_window`, `extract_samples`, `rank_by_distance`,
`score_sample`. `fetch_pool`/`run` (the live MCP calls) are exercised only by
the live protocol run documented in reports/GATE-RERUN-2026-07-23.md, not here.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "eval_ranking.py"
_spec = importlib.util.spec_from_file_location("eval_ranking", _SCRIPT)
assert _spec is not None and _spec.loader is not None
er = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(er)


# --- _haversine_km ---------------------------------------------------------
def test_haversine_zero_distance_for_identical_points():
    assert er._haversine_km(48.8566, 2.3522, 48.8566, 2.3522) == 0.0


def test_haversine_paris_lyon_is_roughly_correct():
    # Paris (48.8566, 2.3522) -> Lyon (45.7640, 4.8357), known ~392 km great-circle.
    km = er._haversine_km(48.8566, 2.3522, 45.7640, 4.8357)
    assert 385 < km < 400


# --- _hour_window (floor start / ceil end) ---------------------------------
def test_hour_window_floors_start_and_ceils_end():
    assert er._hour_window("07:30", "13:30") == (7, 14)


def test_hour_window_exact_hours_unchanged():
    assert er._hour_window("08:00", "12:00") == (8, 12)


def test_hour_window_none_when_either_side_missing():
    assert er._hour_window(None, "12:00") is None
    assert er._hour_window("08:00", None) is None


# --- extract_samples: no-silent-skip discipline ----------------------------
def _turn(turn_index, hotels=None, active_filters=None):
    return {
        "turn": turn_index,
        "response": {"hotels": hotels or [], "active_filters": active_filters or {}},
    }


def test_extract_samples_finds_first_eligible_turn():
    report = {
        "results": [
            {
                "id": "case-1",
                "suite": "geo",
                "turns": [
                    _turn(1, hotels=[{"id": 11}], active_filters={"distance_origin": {"latitude": 48.8, "longitude": 2.3}, "date": "2026-07-25"}),
                ],
            }
        ]
    }
    samples, skips = er.extract_samples(report)
    assert len(samples) == 1
    assert samples[0]["case_id"] == "case-1"
    assert samples[0]["shown_ids"] == [11]
    assert sum(skips.values()) == 0


def test_extract_samples_counts_no_anchor_skip():
    report = {
        "results": [
            {
                "id": "case-2",
                "suite": "geo",
                "turns": [_turn(1, hotels=[{"id": 11}], active_filters={"distance_origin": None, "date": "2026-07-25"})],
            }
        ]
    }
    samples, skips = er.extract_samples(report)
    assert samples == []
    assert skips["no_anchor"] == 1


def test_extract_samples_counts_no_hotel_bearing_turn():
    report = {"results": [{"id": "case-3", "suite": "geo", "turns": [_turn(1, hotels=[])]}]}
    samples, skips = er.extract_samples(report)
    assert samples == []
    assert skips["no_hotel_bearing_turn"] == 1


def test_extract_samples_maps_amenities_to_equipment_ids():
    report = {
        "results": [
            {
                "id": "case-4",
                "suite": "geo",
                "turns": [
                    _turn(
                        1,
                        hotels=[{"id": 11}],
                        active_filters={
                            "distance_origin": {"latitude": 48.8, "longitude": 2.3},
                            "date": "2026-07-25",
                            "amenities": ["pool", "spa"],
                        },
                    )
                ],
            }
        ]
    }
    samples, _ = er.extract_samples(report)
    assert samples[0]["hotel_equipment_ids"] == sorted({33, 34, 2982, 3000, 3001, 35})


# --- rank_by_distance -------------------------------------------------------
def test_rank_by_distance_sorts_nearest_first():
    anchor = (48.8566, 2.3522)  # Paris
    pool = [
        {"hotelId": 1, "lat": 45.7640, "lon": 4.8357},  # Lyon, far
        {"hotelId": 2, "lat": 48.8600, "lon": 2.3500},  # Paris, near
        {"hotelId": 3, "lat": 48.8700, "lon": 2.3600},  # Paris, a bit further
    ]
    ranked = er.rank_by_distance(pool, *anchor)
    assert ranked == [2, 3, 1]


def test_rank_by_distance_skips_hotels_without_coords():
    pool = [{"hotelId": 1, "lat": None, "lon": None}, {"hotelId": 2, "lat": 48.86, "lon": 2.35}]
    ranked = er.rank_by_distance(pool, 48.8566, 2.3522)
    assert ranked == [2]


# --- score_sample: precision@5 / NDCG@5 ------------------------------------
def test_score_sample_perfect_match_is_precision_and_ndcg_1():
    shown = [10, 20, 30, 40, 50]
    truth = [10, 20, 30, 40, 50, 60]
    result = er.score_sample(shown, truth)
    assert result["precision_at_5"] == 1.0
    assert result["ndcg_at_5"] == 1.0


def test_score_sample_no_overlap_is_zero():
    shown = [1, 2, 3, 4, 5]
    truth = [10, 20, 30, 40, 50]
    result = er.score_sample(shown, truth)
    assert result["precision_at_5"] == 0.0
    assert result["ndcg_at_5"] == 0.0


def test_score_sample_partial_overlap_and_order_sensitivity():
    # true top-5 = [10,20,30,40,50]; shown has the true #1 pushed to position 5
    # instead of position 1 — same set overlap (precision unaffected) but NDCG
    # must be lower than the perfect-order case since it discounts rank.
    shown_in_order = [10, 20, 30, 40, 50]
    shown_out_of_order = [20, 30, 40, 50, 10]
    truth = [10, 20, 30, 40, 50]
    perfect = er.score_sample(shown_in_order, truth)
    reordered = er.score_sample(shown_out_of_order, truth)
    assert perfect["precision_at_5"] == reordered["precision_at_5"] == 1.0
    assert reordered["ndcg_at_5"] < perfect["ndcg_at_5"]


def test_score_sample_empty_pool_returns_none():
    assert er.score_sample([1, 2, 3], []) is None
