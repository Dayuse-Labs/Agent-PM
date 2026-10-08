"""Ground-truth block tests (S06) — adapted from agent-usa's
AgentOrchestrator._shortlist_ground_truth_block tests onto this spine's own
SearchResponse.results shape (contract.py) and SessionProfile (profile.py).
"""
from __future__ import annotations

from b2c_concierge.ground_truth import (
    MAX_AMENITIES,
    MAX_HOTELS,
    shortlist_ground_truth_block,
    synthesis_angle,
)
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
    def test_actual_offer_date_and_slot_reach_synthesis(self):
        block = shortlist_ground_truth_block({"results": [{
            "name": "Day room", "offer_date": "2026-10-08", "price": "€75.05",
            "timeslots": [{"start": "11:00", "end": "15:30"}],
        }]}, _profile(date="2026-10-09", timeslot_start="10:00", timeslot_end="18:00"))
        assert "2026-10-08" in block
        assert "11:00–15:30" in block
        assert "10:00–18:00" not in block  # requested window is not an offered slot

    def test_missing_or_malformed_slot_is_not_fabricated_from_request(self):
        block = shortlist_ground_truth_block({"results": [{
            "name": "Day room", "timeslots": [{"start": "unknown", "end": "25:00"}],
        }]}, _profile(timeslot_start="11:00", timeslot_end="16:00"))
        assert "11:00–16:00" not in block
        assert "unknown–25:00" not in block

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


class TestSynthesisAngle:
    """S-PERF5: the reply's variety comes from the DATA, in code. These lock the
    PRECEDENCE (the most decision-changing fact wins) and, above all, that a
    shortlist with nothing notable yields NO angle — an always-on angle would
    just be a new template, which is the defect being fixed."""

    @staticmethod
    def _hotel(**kwargs):
        base = {"name": "H", "price_eur_cents": 9000, "rating": 4.5, "rating_count": 40}
        base.update(kwargs)
        return base

    def test_unremarkable_shortlist_gets_no_angle(self):
        hotels = [
            self._hotel(name="A", price_eur_cents=9000, distance_km=1.1),
            self._hotel(name="B", price_eur_cents=8900, distance_km=3.8),
        ]
        assert synthesis_angle({"results": hotels})[1] == ""

    def test_no_results_gets_no_angle(self):
        assert synthesis_angle({"results": []})[1] == ""
        assert synthesis_angle(None)[1] == ""

    def test_single_result_does_not_prove_exhaustive_inventory(self):
        angle = synthesis_angle({"results": [self._hotel()]})[1]
        assert "current result contains one hotel" in angle
        assert "not exhaustive inventory" in angle
        assert "Only ONE hotel matches" not in angle

    def test_distance_fact_does_not_invent_centrality_or_preference(self):
        # Also carries a wide price spread — distance must take precedence.
        hotels = [
            self._hotel(name="A", price_eur_cents=6000, distance_km=9.0),
            self._hotel(name="B", price_eur_cents=15000, distance_km=14.0),
        ]
        angle = synthesis_angle({"results": hotels})[1]
        assert "from the search origin" in angle
        assert "origin may be a landmark" in angle
        assert "customer's stated preference" in angle
        assert "9-14 km" in angle

    def test_one_central_option_defeats_the_distance_angle(self):
        hotels = [
            self._hotel(name="A", price_eur_cents=9000, distance_km=1.0),
            self._hotel(name="B", price_eur_cents=9100, distance_km=14.0),
        ]
        assert synthesis_angle({"results": hotels})[0] != "distance"

    def test_deep_discount_is_named_with_its_hotel(self):
        hotels = [
            self._hotel(name="Cheap Palace", price_eur_cents=5000,
                        timeslots=[{"original_price": 150.0}]),
            self._hotel(name="B", price_eur_cents=5200, timeslots=[{"original_price": 60.0}]),
        ]
        angle = synthesis_angle({"results": hotels})[1]
        assert "Cheap Palace" in angle
        assert "67%" in angle  # 50 € off a 150 € night rate

    def test_a_shallow_discount_does_not_trigger_the_saving_angle(self):
        hotels = [
            self._hotel(name="A", price_eur_cents=9000, timeslots=[{"original_price": 135.0}]),
            self._hotel(name="B", price_eur_cents=8900, timeslots=[{"original_price": 135.0}]),
        ]
        assert "below its night rate" not in synthesis_angle({"results": hotels})[1]

    def test_wide_price_spread_reports_the_range_in_euros(self):
        hotels = [
            self._hotel(name="A", price_eur_cents=6000),
            self._hotel(name="B", price_eur_cents=15000),
        ]
        angle = synthesis_angle({"results": hotels})[1]
        assert "60-150 €" in angle

    def test_thin_review_base_is_flagged_when_every_score_is_thin(self):
        hotels = [
            self._hotel(name="A", price_eur_cents=9000, rating=5, rating_count=1),
            self._hotel(name="B", price_eur_cents=9100, rating=4.8, rating_count=2),
        ]
        assert "1-2 reviews" in synthesis_angle({"results": hotels})[1]

    def test_one_well_reviewed_hotel_defeats_the_thin_rating_angle(self):
        hotels = [
            self._hotel(name="A", price_eur_cents=9000, rating=5, rating_count=1),
            self._hotel(name="B", price_eur_cents=9100, rating=4.8, rating_count=40),
        ]
        assert synthesis_angle({"results": hotels})[1] == ""

    def test_unrated_hotels_are_ignored_by_the_thin_rating_angle(self):
        # rating 0 = "no score shown on the card" (S-CX9 guard), not a thin score.
        hotels = [
            self._hotel(name="A", price_eur_cents=9000, rating=0, rating_count=0),
            self._hotel(name="B", price_eur_cents=9100, rating=0, rating_count=0),
        ]
        assert synthesis_angle({"results": hotels})[1] == ""

    def test_angle_is_deterministic_for_the_same_shortlist(self):
        hotels = [
            self._hotel(name="A", price_eur_cents=6000),
            self._hotel(name="B", price_eur_cents=15000),
        ]
        first = synthesis_angle({"results": hotels})
        assert first == synthesis_angle({"results": hotels})
        assert first[1] != ""


class TestSynthesisAngleAntiRepeat:
    """The defect this exists for, seen in the browser 2026-07-29: two searches
    in a row kept the same top hotel, so both replies opened on "économie
    impressionnante … 66 %" — the feature meant to create variety produced a new
    template instead. Excluding LAST turn's key is what breaks the tie."""

    @staticmethod
    def _hotels():
        return [
            {"name": "Deal Palace", "price_eur_cents": 5000, "rating": 4.5, "rating_count": 40,
             "timeslots": [{"original_price": 150.0}], "distance_km": 1.0},
            {"name": "B", "price_eur_cents": 15000, "rating": 4.6, "rating_count": 30,
             "timeslots": [{"original_price": 160.0}], "distance_km": 2.0},
        ]

    def test_first_turn_takes_the_top_ranked_angle(self):
        key, directive = synthesis_angle({"results": self._hotels()})
        assert key == "discount"
        assert "Deal Palace" in directive

    def test_excluding_last_turns_key_falls_through_to_the_next_angle(self):
        key, directive = synthesis_angle({"results": self._hotels()}, exclude="discount")
        assert key == "spread"          # same data, DIFFERENT angle
        assert "50-150 €" in directive

    def test_falls_all_the_way_through_to_no_angle(self):
        # Only one candidate qualifies; excluding it must yield no angle at all
        # rather than repeating it.
        hotels = [
            {"name": "A", "price_eur_cents": 9000, "rating": 4.5, "rating_count": 40,
             "distance_km": 9.0},
            {"name": "B", "price_eur_cents": 9100, "rating": 4.6, "rating_count": 30,
             "distance_km": 14.0},
        ]
        assert synthesis_angle({"results": hotels})[0] == "distance"
        assert synthesis_angle({"results": hotels}, exclude="distance") == ("", "")

    def test_an_unrelated_exclusion_changes_nothing(self):
        assert synthesis_angle({"results": self._hotels()}, exclude="thin_ratings")[0] == "discount"

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
        assert "Monday, July 27, 2026" in block and "2026-07-27" not in block
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
        assert "Tuesday, July 28, 2026" in block and "Monday, July 27, 2026" in block
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
        assert "SEARCH DATE: these results are for Tuesday, July 28, 2026" in block

    def test_the_date_is_written_out_in_the_turn_language(self):
        # QA 2026-09-08 n°2: an ISO date in the prompt was copied verbatim into
        # the reply ("Pour demain (2026-09-24)…").
        block = shortlist_ground_truth_block(
            {
                "results": [{"name": "Villa Paris Orly"}],
                "search_date": {"date": "2026-09-24", "same_day": False},
            },
            _profile(),
            "fr",
        )
        assert "jeudi 24 septembre 2026" in block
        assert "2026-09-24" not in block

    def test_a_leaf_without_the_key_changes_nothing(self):
        # Contract safety: an older leaf (or a find_hotel_by_name turn) sends no
        # search_date at all — the block must be byte-identical to before.
        assert shortlist_ground_truth_block(
            {"results": [{"name": "Villa"}]}, _profile()
        ) == shortlist_ground_truth_block({"results": [{"name": "Villa"}]}, _profile())
        assert "SEARCH DATE" not in shortlist_ground_truth_block(
            {"results": [{"name": "Villa"}]}, _profile()
        )


class TestExactWindowEvidence:
    def test_wider_offer_covers_requested_minutes(self):
        block = shortlist_ground_truth_block(
            {"results": [{"name": "Example", "timeslots": [{"start": "10:00", "end": "18:00"}]}]},
            _profile(requested_window={"start": "10:30", "end": "17:00"}),
        )
        assert "10:30–17:00: covered" in block
        assert "does not require arriving earlier" in block

    def test_rounded_site_match_does_not_prove_minute_coverage(self):
        block = shortlist_ground_truth_block(
            {"results": [{"name": "Example", "timeslots": [{"start": "10:00", "end": "17:00"}]}]},
            _profile(requested_window={"start": "10:30", "end": "17:15"}),
        )
        assert "10:30–17:15: not covered" in block

    def test_multiple_offers_must_not_be_stitched_together(self):
        block = shortlist_ground_truth_block(
            {"results": [{"name": "Example", "timeslots": [
                {"start": "10:00", "end": "13:00"}, {"start": "13:00", "end": "18:00"}
            ]}]}, _profile(requested_window={"start": "10:30", "end": "17:00"}),
        )
        assert "10:30–17:00: not covered" in block

    def test_missing_offer_times_are_unknown(self):
        block = shortlist_ground_truth_block(
            {"results": [{"name": "Example"}]},
            _profile(requested_window={"start": "10:30", "end": "17:00"}),
        )
        assert "10:30–17:00: unknown" in block

    def test_missing_request_bound_does_not_invent_full_window(self):
        block = shortlist_ground_truth_block(
            {"results": [{"name": "Example", "timeslots": [{"start": "10:00", "end": "18:00"}]}]},
            _profile(requested_window={"start": "10:30", "end": None}),
        )
        assert "minute coverage" not in block


class TestNamedOfferDateEvidence:
    def test_inline_named_offer_date_is_explicit_without_search_metadata(self):
        from b2c_concierge.ground_truth import date_context_block
        block = date_context_block({'results': [{'name': 'Named hotel', 'offer_id': 'verified-offer',
                                               'offer_date': '2026-10-08',
                                               'timeslots': [{'start': '10:00', 'end': '17:00'}]}]}, 'en')
        assert 'SEARCH DATE' in block and 'October' in block and '2026' in block

    def test_identity_card_does_not_prove_dated_availability(self):
        from b2c_concierge.ground_truth import date_context_block
        assert date_context_block({'results': [{'name': 'Named hotel', 'offer_date': '2026-10-08'}]}) == ''

    def test_different_offer_dates_cannot_be_collapsed_into_one_day(self):
        from b2c_concierge.ground_truth import date_context_block
        results = [{'name': 'Hotel', 'offer_id': str(i), 'offer_date': day,
                    'timeslots': [{'start': '10:00', 'end': '17:00'}]}
                   for i, day in enumerate(('2026-10-08', '2026-10-09'))]
        assert date_context_block({'results': results}) == ''


def test_property_conditions_reach_synthesis_with_hotel_scope():
    from b2c_concierge.ground_truth import shortlist_ground_truth_block
    from b2c_concierge.profile import SessionProfile

    text = shortlist_ground_truth_block({'results': [
        {'id': 1, 'name': 'Example Hotel', 'hotel_conditions': 'Minimum check-in age: 21.'},
        {'id': 2, 'name': 'Another Hotel'},
    ]}, SessionProfile())
    assert 'Minimum check-in age: 21.' in text
    assert 'property only' in text
    assert 'does not establish' in text


def test_long_property_conditions_are_marked_incomplete():
    from b2c_concierge.ground_truth import shortlist_ground_truth_block
    from b2c_concierge.profile import SessionProfile

    text = shortlist_ground_truth_block({'results': [
        {'id': 1, 'name': 'Example Hotel', 'hotel_conditions': 'x' * 10000 + ' Minimum age: 21.'},
    ]}, SessionProfile())
    assert 'truncated' in text
    assert len(text) < 7500


def test_faq_evidence_keeps_general_and_property_policy_scopes_separate():
    from b2c_concierge.ground_truth import faq_ground_truth_block

    text = faq_ground_truth_block({'faq_evidence': [{'hotel': {'hotelId': 12},
        'sections': {'hotelConditions': 'Deposit $250.'},
        'generalFaq': [{'body': 'US booking age is typically 21.'}]}]})
    assert 'Deposit $250.' in text and 'US booking age is typically 21.' in text
    assert 'not a property-specific' in text
    assert faq_ground_truth_block({}) == ''


def test_empty_faq_evidence_exposes_missing_source_instead_of_policy_authority():
    from b2c_concierge.ground_truth import faq_ground_truth_block
    assert faq_ground_truth_block({}) == ''
    block = faq_ground_truth_block({'faq_evidence': [], 'faq_diagnostics': {'source_verified': False}})
    assert 'No verified policy source' in block
    assert 'original successful tool results' not in block
