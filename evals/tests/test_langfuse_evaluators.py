"""Offline unit tests for evals/langfuse_evaluators.py — no network, no LLM.

Constructs fabricated `output` dicts (the shape evals/langfuse_experiment.py's
task function produces) and checks each evaluator's verdict directly, so the
scoring logic is verified independently of ever calling the real facade."""
from __future__ import annotations

from evals.langfuse_evaluators import response_evaluator, trace_evaluator


def _by_name(evaluations: list) -> dict:
    return {e.name: e for e in evaluations}


def _output(response: dict, trace: dict | None = None) -> dict:
    return {"response": response, "trace": trace or {}}


# --- response_evaluator -------------------------------------------------------
def test_min_hotels_pass_and_fail():
    expected = {"min_hotels": 2}
    ok = response_evaluator(
        input=None, output=_output({"hotels": [{}, {}, {}]}), expected_output=expected, metadata=None
    )
    assert _by_name(ok)["min_hotels"].value == 1

    bad = response_evaluator(
        input=None, output=_output({"hotels": [{}]}), expected_output=expected, metadata=None
    )
    assert _by_name(bad)["min_hotels"].value == 0


def test_min_hotels_clarify_allowed_saves_a_zero_count():
    expected = {"min_hotels": 1, "clarify_allowed": True}
    out = _output({"hotels": [], "requires_clarification": True})
    result = _by_name(response_evaluator(input=None, output=out, expected_output=expected, metadata=None))
    assert result["min_hotels"].value == 1


def test_hotels_within_km_flags_a_far_hotel():
    expected = {"hotels_within_km": {"lat": 48.8698, "lon": 2.3078, "km": 3}}
    hotels = [
        {"name": "Near", "latitude": 48.87, "longitude": 2.31},
        {"name": "Far", "latitude": 40.0, "longitude": 2.31},
    ]
    result = _by_name(
        response_evaluator(
            input=None, output=_output({"hotels": hotels}), expected_output=expected, metadata=None
        )
    )
    assert result["hotels_within_km"].value == 0
    assert "Far" in result["hotels_within_km"].comment


def test_hotels_within_km_vacuously_passes_on_empty_results():
    expected = {"hotels_within_km": {"lat": 48.8698, "lon": 2.3078, "km": 3}, "min_hotels": 0}
    result = _by_name(
        response_evaluator(input=None, output=_output({"hotels": []}), expected_output=expected, metadata=None)
    )
    assert result["hotels_within_km"].value == 1


def test_if_resolved_country_code_skips_when_clarified():
    expected = {"if_resolved_country_code": "FR"}
    out = _output({"requires_clarification": True, "active_filters": {}})
    result = _by_name(response_evaluator(input=None, output=out, expected_output=expected, metadata=None))
    assert result["if_resolved_country_code"].value == "skipped"


def test_active_filters_include_subset_list_and_scalar():
    expected = {"active_filters_include": {"adults": 2, "amenities": ["pool"]}}
    good = _output({"active_filters": {"adults": 2, "amenities": ["pool", "spa"]}})
    result = _by_name(response_evaluator(input=None, output=good, expected_output=expected, metadata=None))
    assert result["active_filters_include"].value == 1

    missing = _output({"active_filters": {"amenities": ["spa"]}})  # no adults key at all, wrong amenity
    result = _by_name(response_evaluator(input=None, output=missing, expected_output=expected, metadata=None))
    assert result["active_filters_include"].value == 0


def test_message_must_not_contain_any():
    expected = {"message_must_not_contain_any": ["Illinois", "Indiana"]}
    ok = _output({"message": "Voici 5 hotels a Paris."})
    result = _by_name(response_evaluator(input=None, output=ok, expected_output=expected, metadata=None))
    assert result["message_must_not_contain_any"].value == 1

    bad = _output({"message": "Il n'y a rien en Illinois."})
    result = _by_name(response_evaluator(input=None, output=bad, expected_output=expected, metadata=None))
    assert result["message_must_not_contain_any"].value == 0


def test_offers_capacity_gte_fails_when_field_absent():
    # Pre-P0-1 baseline: the card has no "capacity" field at all yet — this
    # must score 0 (a "target" item), never be silently skipped.
    expected = {"offers_capacity_gte": 2}
    out = _output({"hotels": [{"name": "H1"}]})
    result = _by_name(response_evaluator(input=None, output=out, expected_output=expected, metadata=None))
    assert result["offers_capacity_gte"].value == 0


def test_declared_keys_only():
    """No expected_output keys declared -> no Evaluations at all."""
    result = response_evaluator(input=None, output=_output({}), expected_output={}, metadata=None)
    assert result == []


# --- trace_evaluator -----------------------------------------------------------
def test_search_offers_args_include_and_absent():
    expected = {"trace": {"search_offers_args_include": {"adults": 2}, "search_offers_args_absent": ["children"]}}
    trace = {"search_offers_args": {"lat": 1.0, "lon": 2.0, "adults": 2}}
    result = _by_name(trace_evaluator(input=None, output=_output({}, trace), expected_output=expected, metadata=None))
    assert result["search_offers_args_include"].value == 1
    assert result["search_offers_args_absent"].value == 1


def test_search_offers_args_missing_trace_skips_not_fails():
    expected = {"trace": {"search_offers_args_include": {"adults": 2}}}
    result = _by_name(
        trace_evaluator(input=None, output=_output({}, {"search_offers_args": None}), expected_output=expected, metadata=None)
    )
    assert result["search_offers_args_include"].value == "skipped"


def test_expected_pick():
    expected = {"trace": {"expected_pick": {"pick": "position", "pick_position": 2}}}
    trace = {"pick": {"pick": "position", "pick_position": 2}}
    result = _by_name(trace_evaluator(input=None, output=_output({}, trace), expected_output=expected, metadata=None))
    assert result["expected_pick"].value == 1


def test_expected_route():
    expected = {"trace": {"expected_route": "booking_confirmed"}}
    trace = {"route": "booking_confirmed"}
    result = _by_name(trace_evaluator(input=None, output=_output({}, trace), expected_output=expected, metadata=None))
    assert result["expected_route"].value == 1

    trace_wrong = {"route": "not_booking_confirmed"}
    result = _by_name(
        trace_evaluator(input=None, output=_output({}, trace_wrong), expected_output=expected, metadata=None)
    )
    assert result["expected_route"].value == 0


def test_trace_evaluator_no_trace_assertions_declared():
    assert trace_evaluator(input=None, output=_output({}), expected_output={"min_hotels": 1}, metadata=None) == []


# --- mcp-dayuse#8: QA 2026-09-30 facts ---------------------------------------
def _card(name, start, end, offer_date=None):
    card = {"name": name, "timeslots": [{"start": start, "end": end}]}
    if offer_date:
        card["offer_date"] = offer_date
    return card


def _score(expected, response):
    return _by_name(response_evaluator(input=None, output=_output(response), expected_output=expected, metadata=None))


def test_cards_cover_window_site_rule():
    expected = {"cards_cover_window": {"start": "22:01", "end": "23:01"}}
    assert _score(expected, {"hotels": [_card("A", "17:00", "23:00")]})["cards_cover_window"].value == 1
    bad = _score(expected, {"hotels": [_card("A", "17:00", "23:00"), _card("B", "17:00", "22:00")]})
    assert bad["cards_cover_window"].value == 0 and "B" in bad["cards_cover_window"].comment


def test_cards_cover_window_accepts_cards_labelled_as_closest():
    expected = {"cards_cover_window": {"start": "06:00", "end": "16:00"}}
    cards = [_card("A", "08:00", "14:00")]
    labelled = {"hotels": cards, "message": "Aucune offre ne couvre tout le créneau ; voici les offres les plus proches."}
    assert _score(expected, labelled)["cards_cover_window"].value == 1
    assert _score(expected, {"hotels": cards, "message": "Voici A."})["cards_cover_window"].value == 0


def test_offers_on_date_days_ahead():
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    day = (datetime.now(ZoneInfo("Europe/Paris")).date() + timedelta(days=2)).isoformat()
    expected = {"offers_on_date": {"days_ahead": 2}}
    assert _score(expected, {"hotels": [_card("A", "10:00", "16:00", day)]})["offers_on_date"].value == 1
    assert _score(expected, {"hotels": [_card("A", "10:00", "16:00", "2000-01-01")]})["offers_on_date"].value == 0
    assert _score(expected, {"hotels": []})["offers_on_date"].value == "skipped"


def test_no_iso_date_in_message_ignores_urls():
    expected = {"no_iso_date_in_message": True}
    ok = {"message": "Voir https://www.dayuse.fr/h?checkinDate=2026-10-07 pour mercredi 7 octobre."}
    assert _score(expected, ok)["no_iso_date_in_message"].value == 1
    assert _score(expected, {"message": "Recherche effectuée pour le 2026-09-30."})["no_iso_date_in_message"].value == 0


def test_first_hotel_name_contains_reads_the_first_card_only():
    # mcp-dayuse#7: the hotel the user named is the first card.
    expected = {"first_hotel_name_contains": "st paul's hotel"}
    assert _score(expected, {"hotels": [{"name": "St Paul's Hotel"}, {"name": "B"}]})[
        "first_hotel_name_contains"
    ].value == 1
    assert _score(expected, {"hotels": [{"name": "B"}, {"name": "St Paul's Hotel"}]})[
        "first_hotel_name_contains"
    ].value == 0
    assert _score(expected, {"hotels": []})["first_hotel_name_contains"].value == 0
