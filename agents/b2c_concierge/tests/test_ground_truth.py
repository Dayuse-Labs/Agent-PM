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

    def test_url_rendered_verbatim_with_the_copy_exactly_rule(self):
        # S-G12: the model may only ever quote the ES-slug url it was shown.
        block = shortlist_ground_truth_block(
            {
                "results": [
                    {
                        "name": "Ibis Rungis",
                        "url": "https://www.dayuse.fr/hotels/france/ibis-rungis-aeroport-paris-orly",
                    }
                ]
            },
            _profile(),
        )
        assert "url: https://www.dayuse.fr/hotels/france/ibis-rungis-aeroport-paris-orly" in block
        assert "copy EXACTLY" in block

    def test_no_url_line_when_the_card_has_none(self):
        block = shortlist_ground_truth_block(
            {"results": [{"name": "Hotel Alameda", "url": "not-https"}]}, _profile()
        )
        assert "url:" not in block

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


class TestSameDayCutoff:
    """S-CX6: an empty SAME-DAY search is a closed booking window, not an empty
    market (measured: cutoffs 05h→16h local, 518-hotel Paris pool dry at 17h50).
    The generic note's "widen the area / raise the budget" menu is wrong there."""

    _CLOSED = {
        "results": [],
        "search_date": {"date": "2026-07-27", "same_day": True, "cutoff_closed": True},
    }

    def test_same_day_dead_end_names_the_day_and_the_cause(self):
        block = shortlist_ground_truth_block(self._CLOSED, _profile(consecutive_empty_searches=1))
        assert "2026-07-27" in block
        assert "CLOSED" in block

    def test_same_day_dead_end_forbids_the_irrelevant_remedies(self):
        block = shortlist_ground_truth_block(self._CLOSED, _profile(consecutive_empty_searches=1))
        # The authoritative note must come AFTER the generic one, or the generic
        # "widen the area, adjust the budget" menu wins the prompt.
        assert block.index("Do NOT suggest widening") > block.index("concrete next step")

    def test_an_empty_market_is_never_blamed_on_a_closed_window(self):
        # Same-day zero with NO cutoff_closed flag = the pool itself was
        # empty (probed: Tokyo, total=0). Claiming "bookings are closed"
        # there would be an invented cause.
        block = shortlist_ground_truth_block(
            {"results": [], "search_date": {"date": "2026-07-27", "same_day": True}},
            _profile(consecutive_empty_searches=1),
        )
        assert "CLOSED" not in block and "ZERO results" in block

    def test_a_future_date_dead_end_keeps_the_generic_note_only(self):
        block = shortlist_ground_truth_block(
            {"results": [], "search_date": {"date": "2026-09-09", "same_day": False}},
            _profile(consecutive_empty_searches=1),
        )
        assert "CLOSED" not in block and "ZERO results" in block

    def test_swapped_day_disclosure_is_mandatory_and_names_both_dates(self):
        block = shortlist_ground_truth_block(
            {
                "results": [{"name": "Villa Paris Orly", "price": "€54.00"}],
                "search_date": {
                    "date": "2026-07-28",
                    "same_day": False,
                    "cutoff_fallback_from": "2026-07-27",
                },
            },
            _profile(),
        )
        assert "MANDATORY DISCLOSURE" in block
        assert "2026-07-28" in block and "2026-07-27" in block
        # Disclosure first: the answer's FIRST sentence has to carry it.
        assert block.index("MANDATORY DISCLOSURE") < block.index("Villa Paris Orly")

    def test_a_normal_search_just_states_its_date(self):
        block = shortlist_ground_truth_block(
            {
                "results": [{"name": "Villa Paris Orly"}],
                "search_date": {"date": "2026-07-28", "same_day": False},
            },
            _profile(),
        )
        assert "SEARCH DATE: these results are for 2026-07-28" in block

    def test_a_leaf_without_the_key_changes_nothing(self):
        # Contract safety: an older leaf (or a find_hotel_by_name turn) sends no
        # search_date at all — the block must be byte-identical to before.
        assert shortlist_ground_truth_block(
            {"results": [{"name": "Villa"}]}, _profile()
        ) == shortlist_ground_truth_block({"results": [{"name": "Villa"}]}, _profile())
        assert "SEARCH DATE" not in shortlist_ground_truth_block(
            {"results": [{"name": "Villa"}]}, _profile()
        )
