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
