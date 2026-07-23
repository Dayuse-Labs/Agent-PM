"""Offline tests for scripts/eval_hardening.py (S-G8, items 1-2-3-4-5-6-7).

All fixtures here are synthetic — pure dicts shaped like a case from
`dayuse_eval_pack/eval_pack/cases/*.jsonl` and a result from a report built by
`eval_pack.runner.build_report`. No network, no live services. The pack
itself is never imported or touched (see module docstring in eval_hardening.py
for why); `tests/test_eval_hardening_fixtures.py`-style cross-checks against
the REAL fixture files live in the "generated from fixtures" tests below,
which read the actual `dayuse_eval_pack/eval_pack/cases/*.jsonl` read-only.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "eval_hardening.py"
_spec = importlib.util.spec_from_file_location("eval_hardening", _SCRIPT)
assert _spec is not None and _spec.loader is not None
eh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eh)

REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_CASES_DIR = REPO_ROOT / "dayuse_eval_pack" / "eval_pack" / "cases"


def _case(case_id="c1", suite="geo", turns=None, tags=None, request_=None, clock=None):
    return {
        "id": case_id,
        "suite": suite,
        "tags": tags or [],
        "request": request_ or {},
        "clock": clock,
        "turns": turns or [],
    }


def _turn(message, expect=None):
    return {"message": message, "expect": expect or []}


def _result_turn(response):
    return {"response": response}


def _result(case_id, responses, suite="geo", passed=True):
    return {
        "id": case_id,
        "suite": suite,
        "passed": passed,
        "turns": [_result_turn(r) for r in responses],
    }


def _response(**overrides):
    base = {"message": "", "hotels": [], "active_filters": {}, "_http_status": 200}
    base.update(overrides)
    return base


# --- item 1: min_hotels coverage gap on geo cases ----------------------------
def test_geo_cases_missing_min_hotels_flags_hotel_countries_without_min_hotels():
    cases = [
        _case(
            "geo-flagged",
            turns=[_turn("x", [{"type": "hotel_countries", "allowed": ["GB"]}])],
        ),
        _case(
            "geo-already-covered",
            turns=[
                _turn(
                    "x",
                    [
                        {"type": "hotel_countries", "allowed": ["IT"]},
                        {"type": "min_hotels", "value": 1},
                    ],
                )
            ],
        ),
        _case(
            "geo-max-zero",
            turns=[_turn("x", [{"type": "hotel_countries", "allowed": ["US"]}, {"type": "max_hotels", "value": 0}])],
        ),
        _case("non-geo", suite="core", turns=[_turn("x", [{"type": "hotel_countries", "allowed": ["FR"]}])]),
    ]
    assert eh.geo_cases_missing_min_hotels(cases) == ["geo-flagged"]


def test_check_min_hotels_added_fails_on_zero_hotels_passes_otherwise():
    case = _case("geo-flagged", turns=[_turn("hi")])
    empty = _result("geo-flagged", [_response(hotels=[])])
    outcomes = eh.check_min_hotels_added(case, empty)
    assert outcomes == [{"check": "min_hotels_added", "turn": 1, "status": "fail", "detail": "0 hotels, expected >= 1"}]

    full = _result("geo-flagged", [_response(hotels=[{"id": 1}])])
    outcomes = eh.check_min_hotels_added(case, full)
    assert outcomes[0]["status"] == "pass"


# --- item 2: 3(+1)-class outcome ---------------------------------------------
@pytest.mark.parametrize(
    "response, expected",
    [
        (_response(_http_status=502), "technical_degradation"),
        (_response(_client_error="TimeoutError: x"), "technical_degradation"),
        (_response(message="I can't reach the hotel search right now"), "technical_degradation"),
        (_response(message="Je n'arrive pas à joindre la recherche d'hôtels"), "technical_degradation"),
        (_response(requires_clarification=True, message="Which Chester — GB or PA?"), "safe_clarification"),
        (_response(hotels=[{"id": 1, "name": "Hotel A"}]), "successful_search"),
        (_response(hotels=[]), "no_result_honest"),
    ],
)
def test_classify_turn_outcome(response, expected):
    assert eh.classify_turn_outcome(response) == expected


def test_classify_case_outcome_uses_last_turn():
    result = _result(
        "c1",
        [
            _response(hotels=[]),  # first turn: clarify-like, irrelevant
            _response(hotels=[{"id": 1}]),  # terminal turn: successful
        ],
    )
    assert eh.classify_case_outcome(result) == "successful_search"


def test_classify_case_outcome_none_when_no_turns():
    assert eh.classify_case_outcome(_result("c1", [])) is None


# --- item 3: anchor resolved on empty shortlist -------------------------------
def test_anchor_resolved_when_empty_pass():
    case = _case("c1", turns=[_turn("hotel in chester")])
    result = _result(
        "c1", [_response(hotels=[], active_filters={"city": "Chester", "country_code": "GB", "resolved_city": "Chester, UK"})]
    )
    outcomes = eh.check_anchor_resolved_when_empty(case, result)
    assert outcomes == [
        {
            "check": "anchor_resolved_empty_shortlist",
            "turn": 1,
            "status": "pass",
            "detail": "country_code='GB' resolved_city='Chester, UK'",
        }
    ]


def test_anchor_resolved_when_empty_fail_on_blank_anchor():
    case = _case("c1", turns=[_turn("hotel in chester")])
    result = _result("c1", [_response(hotels=[], active_filters={"city": "Chester", "country_code": None, "resolved_city": None})])
    outcomes = eh.check_anchor_resolved_when_empty(case, result)
    assert outcomes[0]["status"] == "fail"


def test_anchor_resolved_when_empty_skips_on_missing_keys():
    case = _case("c1", turns=[_turn("hotel in chester")])
    result = _result("c1", [_response(hotels=[], active_filters={"city": "Chester"})])
    outcomes = eh.check_anchor_resolved_when_empty(case, result)
    assert outcomes[0]["status"] == "skipped"


def test_anchor_resolved_not_applicable_when_hotels_present_or_no_city():
    case = _case("c1", turns=[_turn("x"), _turn("y")])
    result = _result(
        "c1",
        [
            _response(hotels=[{"id": 1}], active_filters={"city": "Paris"}),  # hotels present -> n/a
            _response(hotels=[], active_filters={}),  # no city -> n/a
        ],
    )
    assert eh.check_anchor_resolved_when_empty(case, result) == []


# --- item 4a: currency per turn -----------------------------------------------
def test_currency_per_turn_pass_and_fail():
    case = _case("c1", request_={"currency": "GBP"}, turns=[_turn("x"), _turn("y")])
    result = _result(
        "c1",
        [
            _response(active_filters={"currency": "GBP"}, hotels=[{"currency": "GBP"}]),
            _response(active_filters={"currency": "EUR"}, hotels=[]),
        ],
    )
    outcomes = eh.check_currency_per_turn(case, result)
    assert outcomes[0]["status"] == "pass"
    assert outcomes[1]["status"] == "fail"


def test_currency_per_turn_skipped_when_field_absent():
    case = _case("c1", request_={"currency": "NZD"}, turns=[_turn("x")])
    result = _result("c1", [_response(hotels=[{"id": 1}], active_filters={})])
    outcomes = eh.check_currency_per_turn(case, result)
    assert outcomes[0]["status"] == "skipped"


def test_currency_per_turn_not_applicable_without_request_currency():
    case = _case("c1", request_={}, turns=[_turn("x")])
    result = _result("c1", [_response()])
    assert eh.check_currency_per_turn(case, result) == []


# --- item 4b: timeslot minutes -------------------------------------------------
def test_timeslot_minutes_catches_rounding_bug():
    case = _case("c1", turns=[_turn("check-in 7:30am checkout 1:30pm")])
    rounded = _result("c1", [_response(active_filters={"timeslot_start": "07:00", "timeslot_end": "13:00"})])
    outcomes = eh.check_timeslot_minutes(case, rounded)
    assert outcomes[0]["status"] == "fail"

    correct = _result("c1", [_response(active_filters={"timeslot_start": "07:30", "timeslot_end": "13:30"})])
    outcomes = eh.check_timeslot_minutes(case, correct)
    assert outcomes[0]["status"] == "pass"


def test_timeslot_minutes_skipped_when_fields_absent():
    case = _case("c1", turns=[_turn("14h30 please")])
    result = _result("c1", [_response(active_filters={})])
    outcomes = eh.check_timeslot_minutes(case, result)
    assert outcomes[0]["status"] == "skipped"


def test_timeslot_minutes_not_applicable_without_explicit_minutes():
    case = _case("c1", turns=[_turn("tomorrow at 11:00")])
    result = _result("c1", [_response(active_filters={"timeslot_start": "11:00"})])
    assert eh.check_timeslot_minutes(case, result) == []


# --- item 4c: zone_change tag --------------------------------------------------
def test_zone_change_pass_when_last_turn_moves_zone():
    case = _case("c1", tags=["zone_change"], turns=[_turn("a"), _turn("b"), _turn("c")])
    result = _result(
        "c1",
        [
            _response(active_filters={"zone": None}),
            _response(active_filters={"zone": "Fort Lauderdale"}),
            _response(active_filters={"zone": "Boca Raton"}),
        ],
    )
    outcome = eh.check_zone_change(case, result)
    assert outcome["status"] == "pass"


def test_zone_change_fail_when_zone_stuck():
    case = _case("c1", tags=["zone_change"], turns=[_turn("a"), _turn("b")])
    result = _result("c1", [_response(active_filters={"zone": "Fort Lauderdale"}), _response(active_filters={"zone": "Fort Lauderdale"})])
    outcome = eh.check_zone_change(case, result)
    assert outcome["status"] == "fail"


def test_zone_change_pass_when_the_place_moves_as_city():
    # D2-a (2026-07-23): the agent records a neighboring-city change under
    # `city`, not `zone` — the check must credit either.
    case = _case("c1", tags=["zone_change"], turns=[_turn("a"), _turn("b")])
    result = _result(
        "c1",
        [
            _response(active_filters={"city": "Miami", "zone": None}),
            _response(active_filters={"city": "Fort Lauderdale", "zone": None}),
        ],
    )
    outcome = eh.check_zone_change(case, result)
    assert outcome["status"] == "pass"


def test_zone_change_none_when_untagged():
    case = _case("c1", tags=[], turns=[_turn("a"), _turn("b")])
    result = _result("c1", [_response(), _response()])
    assert eh.check_zone_change(case, result) is None


def test_zone_change_skipped_when_field_absent():
    case = _case("c1", tags=["zone_change"], turns=[_turn("a"), _turn("b")])
    result = _result("c1", [_response(active_filters={}), _response(active_filters={})])
    outcome = eh.check_zone_change(case, result)
    assert outcome["status"] == "skipped"


# --- item 4d: named_hotel_present tag -------------------------------------------
def test_named_hotel_present_pass_and_fail():
    case = _case("c1", tags=["named_hotel_present"], turns=[_turn("a")])
    resolved = _result("c1", [_response(active_filters={"named_hotel": {"hotel_id": 42, "name": "X"}})])
    assert eh.check_named_hotel_present(case, resolved)["status"] == "pass"

    lost = _result("c1", [_response(active_filters={"named_hotel": None})])
    assert eh.check_named_hotel_present(case, lost)["status"] == "fail"


def test_named_hotel_present_skipped_when_field_absent():
    case = _case("c1", tags=["named_hotel_present"], turns=[_turn("a")])
    result = _result("c1", [_response(active_filters={})])
    assert eh.check_named_hotel_present(case, result)["status"] == "skipped"


# --- item 4e: date_reference from frozen clock + today/tomorrow ----------------
def test_date_reference_pass_and_fail():
    case = _case("c1", clock="2026-07-10T10:00:00Z", turns=[_turn("hotel for tomorrow")])
    correct = _result("c1", [_response(active_filters={"date": "2026-07-11"})])
    outcomes = eh.check_date_reference(case, correct)
    assert outcomes[0]["status"] == "pass"

    wrong = _result("c1", [_response(active_filters={"date": "2026-07-10"})])
    outcomes = eh.check_date_reference(case, wrong)
    assert outcomes[0]["status"] == "fail"


def test_date_reference_today_french():
    case = _case("c1", clock="2026-07-10T10:00:00Z", turns=[_turn("un hotel aujourd'hui")])
    result = _result("c1", [_response(active_filters={"date": "2026-07-10"})])
    outcomes = eh.check_date_reference(case, result)
    assert outcomes[0]["status"] == "pass"


def test_date_reference_skipped_when_field_absent():
    case = _case("c1", clock="2026-07-10T10:00:00Z", turns=[_turn("hotel tomorrow")])
    result = _result("c1", [_response(active_filters={})])
    outcomes = eh.check_date_reference(case, result)
    assert outcomes[0]["status"] == "skipped"


def test_date_reference_not_applicable_without_keyword():
    case = _case("c1", clock="2026-07-10T10:00:00Z", turns=[_turn("hotel in Paris")])
    result = _result("c1", [_response(active_filters={"date": None})])
    assert eh.check_date_reference(case, result) == []


# --- item 5: distance verifiability ---------------------------------------------
def _proximity_case(turns):
    return _case(
        "c1",
        suite="prod_wounds",
        turns=[_turn(m, [{"type": "distance_accuracy", "origin": [48.85, 2.35]}]) for m in turns],
    )


def test_distance_verifiable_fail_on_missing_value_when_supported():
    case = _proximity_case(["near me"])
    result = _result("c1", [_response(hotels=[{"name": "A", "distance_km": 3.0}, {"name": "B", "distance_km": None}])])
    outcomes = eh.check_distance_verifiable(case, result)
    assert outcomes[0]["status"] == "fail"


def test_distance_verifiable_pass_when_all_present():
    case = _proximity_case(["near me"])
    result = _result("c1", [_response(hotels=[{"name": "A", "distance_km": 3.0}])])
    outcomes = eh.check_distance_verifiable(case, result)
    assert outcomes[0]["status"] == "pass"


def test_distance_verifiable_skipped_when_unsupported():
    case = _proximity_case(["near me"])
    result = _result("c1", [_response(hotels=[{"name": "A"}])])
    outcomes = eh.check_distance_verifiable(case, result)
    assert outcomes[0]["status"] == "skipped"


def test_distance_verifiable_not_applicable_without_proximity_requirement():
    case = _case("c1", suite="core", turns=[_turn("hotel in paris")])
    result = _result("c1", [_response(hotels=[{"name": "A"}])])
    assert eh.check_distance_verifiable(case, result) == []


def test_distance_verifiable_empty_shortlist_not_applicable():
    case = _proximity_case(["near me"])
    result = _result("c1", [_response(hotels=[])])
    assert eh.check_distance_verifiable(case, result) == []


# --- item 6: "other options" -----------------------------------------------------
def test_other_options_turns_detects_message_and_skips_turn_one():
    case = _case("c1", turns=[_turn("Show me different options"), _turn("first search"), _turn("Show me other options")])
    assert eh.other_options_turns(case) == [3]


def test_check_other_options_pass_on_new_ids():
    case = _case("c1", turns=[_turn("first search"), _turn("Show me different options")])
    result = _result(
        "c1",
        [
            _response(hotels=[{"id": 1}, {"id": 2}]),
            _response(hotels=[{"id": 2}, {"id": 3}]),  # id 3 is new
        ],
    )
    outcomes = eh.check_other_options(case, result)
    assert outcomes[0]["status"] == "pass"


def test_check_other_options_pass_on_exhaustion_disclosure():
    case = _case("c1", turns=[_turn("first search"), _turn("Show me different options")])
    result = _result(
        "c1",
        [
            _response(hotels=[{"id": 1}]),
            _response(hotels=[{"id": 1}], message="Even after widening the budget, I still couldn't find anything else."),
        ],
    )
    outcomes = eh.check_other_options(case, result)
    assert outcomes[0]["status"] == "pass"


def test_check_other_options_fail_on_repeat_without_disclosure():
    case = _case("c1", turns=[_turn("first search"), _turn("Show me different options")])
    result = _result("c1", [_response(hotels=[{"id": 1}]), _response(hotels=[{"id": 1}], message="Here they are again.")])
    outcomes = eh.check_other_options(case, result)
    assert outcomes[0]["status"] == "fail"


def test_check_other_options_not_applicable_when_previous_turn_empty():
    case = _case("c1", turns=[_turn("first search"), _turn("Show me different options")])
    result = _result("c1", [_response(hotels=[]), _response(hotels=[{"id": 1}])])
    assert eh.check_other_options(case, result) == []


# --- item 7: triple report -------------------------------------------------------
def test_build_triple_report_separates_raw_excluded_and_timeout():
    results = [
        _result("ok-1", [_response(hotels=[{"id": 1}])], passed=True),
        _result("ok-2", [_response(hotels=[{"id": 1}])], passed=True),
        _result("degraded-1", [_response(_http_status=502)], passed=False),
        _result("timeout-1", [_response(_http_status=599, _client_error="TimeoutError: x")], passed=False),
        _result("genuine-fail", [_response(hotels=[])], passed=False),
    ]
    report = eh.build_triple_report(results)
    assert report["raw"] == {"total": 5, "passed": 2, "pass_rate": 0.4}
    excl = report["excluding_technical_degradation"]
    assert excl["excluded_case_ids"] == ["degraded-1", "timeout-1"]
    assert excl["total"] == 3
    assert excl["passed"] == 2
    timeout = report["timeout_rate"]
    assert timeout["turn_timeouts"] == 1
    assert timeout["case_ids_with_timeout"] == ["timeout-1"]


def test_build_triple_report_empty_results():
    report = eh.build_triple_report([])
    assert report["raw"]["pass_rate"] == 0.0
    assert report["timeout_rate"]["turn_timeout_rate"] == 0.0


# --- orchestration ----------------------------------------------------------------
def test_annotate_result_skips_when_case_not_found():
    result = _result("unknown-id", [_response()])
    annotation = eh.annotate_result(None, result)
    assert annotation["checks"] == [{"check": "case_lookup", "turn": 0, "status": "skipped", "detail": "case id not found in --cases-dir fixtures"}]
    assert annotation["case_outcome"] == "no_result_honest"


def test_annotate_report_end_to_end():
    case = _case(
        "geo-flagged",
        turns=[_turn("x", [{"type": "hotel_countries", "allowed": ["GB"]}])],
    )
    result = _result("geo-flagged", [_response(hotels=[])], passed=False)
    report = {"endpoint": "http://x", "results": [result]}
    annotated = eh.annotate_report(report, {"geo-flagged": case})
    assert annotated["triple_report"]["raw"]["total"] == 1
    assert annotated["cases"][0]["checks"][0]["check"] == "min_hotels_added"
    assert annotated["cases"][0]["checks"][0]["status"] == "fail"


def test_load_cases_reads_jsonl(tmp_path):
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    (cases_dir / "geo.jsonl").write_text(
        json.dumps({"id": "geo-1", "suite": "geo", "turns": [{"message": "x", "expect": []}]}) + "\n",
        encoding="utf-8",
    )
    cases = eh.load_cases(cases_dir)
    assert set(cases) == {"geo-1"}
    assert cases["geo-1"]["suite"] == "geo"


# --- item 1, generated from the REAL fixtures (not hand-picked) -------------------
@pytest.mark.skipif(not REAL_CASES_DIR.exists(), reason="dayuse_eval_pack fixtures not present in this checkout")
def test_geo_cases_missing_min_hotels_against_real_fixtures():
    cases = list(eh.load_cases(REAL_CASES_DIR).values())
    missing = eh.geo_cases_missing_min_hotels(cases)
    # A fixed, mechanically-derived set — regenerate by re-running this
    # function if the pack's own fixtures ever change (the pack itself is
    # never edited by this harness, but this locks today's known gap so a
    # silent pack update doesn't go unnoticed).
    assert set(missing) == {
        "geo-birmingham-airport-5a211115",
        "geo-budapest-4d5b6c69",
        "geo-kingston-thames-762813c8",
        "geo-halifax-gbp-0423d9d8",
        "geo-athens-gr-homonym",
        "geo-charleston-gb-homonym",
        "geo-between-cities-multi",
    }
