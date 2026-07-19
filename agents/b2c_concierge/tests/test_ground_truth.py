"""Ground-truth block tests (S06) — adapted from agent-usa's
AgentOrchestrator._shortlist_ground_truth_block tests onto this spine's own
SearchResponse.results shape (contract.py) and SessionProfile (profile.py).
"""
from __future__ import annotations

from b2c_concierge.ground_truth import MAX_AMENITIES, MAX_HOTELS, shortlist_ground_truth_block
from b2c_concierge.profile import SessionProfile


def _profile(**kwargs) -> SessionProfile:
    return SessionProfile(**kwargs)


class TestEmptyBlock:
    def test_no_results_and_no_streak_is_empty(self):
        assert shortlist_ground_truth_block({}, _profile()) == ""
        assert shortlist_ground_truth_block({"results": []}, _profile()) == ""

    def test_missing_response_is_empty(self):
        assert shortlist_ground_truth_block(None, _profile()) == ""


class TestEmptyScreenNote:
    def test_zero_results_with_streak_flags_the_empty_screen(self):
        block = shortlist_ground_truth_block(
            {"results": []}, _profile(consecutive_empty_searches=1)
        )
        assert "ZERO results" in block

    def test_missing_results_key_with_streak_also_flags_it(self):
        block = shortlist_ground_truth_block({}, _profile(consecutive_empty_searches=3))
        assert "ZERO results" in block


class TestShortlistRendering:
    def test_lists_hotel_name_place_price_and_amenities(self):
        block = shortlist_ground_truth_block(
            {
                "results": [
                    {
                        "name": "Hotel Alameda",
                        "city": "New York",
                        "price": "from $110.60",
                        "amenities": ["Rooftop pool", "Restaurant"],
                    }
                ]
            },
            _profile(),
        )
        assert "GROUND TRUTH" in block
        assert "Hotel Alameda" in block
        assert "New York" in block
        assert "from $110.60" in block
        assert "Rooftop pool" in block
        assert "ALREADY ran" in block

    def test_does_not_replace_tool_calls_disclaimer_is_present(self):
        block = shortlist_ground_truth_block(
            {"results": [{"name": "Hotel Alameda"}]}, _profile()
        )
        assert "does NOT replace tool calls" in block

    def test_missing_amenities_render_as_none_listed(self):
        block = shortlist_ground_truth_block(
            {"results": [{"name": "Hotel Alameda"}]}, _profile()
        )
        assert "none listed" in block

    def test_rating_rendered_when_present(self):
        block = shortlist_ground_truth_block(
            {"results": [{"name": "Hotel Alameda", "rating": 4.6}]}, _profile()
        )
        assert "rating 4.6/5" in block

    def test_fresh_results_never_show_the_empty_screen_note(self):
        block = shortlist_ground_truth_block(
            {"results": [{"name": "Hotel Alameda"}]},
            _profile(consecutive_empty_searches=0),
        )
        assert "ZERO results" not in block


class TestCaps:
    def test_hotels_capped_at_max_hotels(self):
        results = [{"name": f"Hotel {i}"} for i in range(MAX_HOTELS + 5)]
        block = shortlist_ground_truth_block({"results": results}, _profile())
        for i in range(MAX_HOTELS):
            assert f"Hotel {i}" in block
        for i in range(MAX_HOTELS, MAX_HOTELS + 5):
            assert f"Hotel {i}" not in block

    def test_amenities_capped_per_hotel(self):
        amenities = [f"Amenity{i}" for i in range(MAX_AMENITIES + 5)]
        block = shortlist_ground_truth_block(
            {"results": [{"name": "Hotel Alameda", "amenities": amenities}]}, _profile()
        )
        for i in range(MAX_AMENITIES):
            assert f"Amenity{i}" in block
        for i in range(MAX_AMENITIES, MAX_AMENITIES + 5):
            assert f"Amenity{i}" not in block

    def test_non_dict_entries_are_skipped_not_crashed_on(self):
        block = shortlist_ground_truth_block(
            {"results": ["not-a-dict", {"name": "Hotel Alameda"}]}, _profile()
        )
        assert "Hotel Alameda" in block
