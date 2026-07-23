from __future__ import annotations

import json

from eval_pack.compare import compare_reports
from eval_pack.runner import _case_payload, evaluate_turn, load_cases


def _case(**overrides):
    value = {
        "id": "distance-case",
        "suite": "prod_wounds",
        "request": {"native_context": {"geolocation": {"lat": 48.8566, "lon": 2.3522}}},
        "turns": [],
    }
    value.update(overrides)
    return value


def test_distance_accuracy_accepts_correct_reported_distance():
    case = _case()
    turn = {
        "message": "Near me",
        "expect": [
            {
                "type": "distance_accuracy",
                "origin": "native_geolocation",
                "tolerance_km": 0.2,
                "tolerance_ratio": 0.01,
            }
        ],
    }
    response = {
        "_http_status": 200,
        "hotels": [
            {
                "name": "Nearby",
                "latitude": 48.8656,
                "longitude": 2.3522,
                "distance_km": 1.0,
            }
        ],
    }

    checks = evaluate_turn(
        case=case,
        turn_index=1,
        turn=turn,
        response=response,
        prior_responses=[],
    )

    assert all(check.passed for check in checks)


def test_distance_accuracy_origin_reads_client_geo_context_device():
    # The real facade contract (S-G2): client_geo_context.device.{latitude,
    # longitude, permission} — decision D1-a (2026-07-23) moved the GPS
    # fixtures to it; "native_geolocation" resolves from either shape.
    case = _case(
        request={
            "client_geo_context": {
                "device": {"latitude": 48.8566, "longitude": 2.3522, "permission": "granted"}
            }
        }
    )
    turn = {
        "message": "Near me",
        "expect": [
            {
                "type": "distance_accuracy",
                "origin": "native_geolocation",
                "tolerance_km": 0.2,
                "tolerance_ratio": 0.01,
            }
        ],
    }
    response = {
        "_http_status": 200,
        "hotels": [
            {"name": "Nearby", "latitude": 48.8656, "longitude": 2.3522, "distance_km": 1.0}
        ],
    }

    checks = evaluate_turn(case=case, turn_index=1, turn=turn, response=response, prior_responses=[])

    assert all(check.passed for check in checks)


def test_case_payload_forwards_client_geo_context():
    geo = {"device": {"latitude": 48.9, "longitude": 2.4, "permission": "granted"}}
    case = _case(request={"client_geo_context": geo})
    payload = _case_payload(case, {"message": "near me"}, "sid")
    assert payload["client_geo_context"] == geo


def test_filter_place_matches_zone_or_city():
    # D2-a (2026-07-23): a place change must count wherever the agent records
    # it — zone for a sub-city area, city/resolved_city for a neighboring city.
    case = _case()
    turn = {"message": "Same budget in Fort Lauderdale", "expect": [{"type": "filter_place", "value": "Fort Lauderdale"}]}
    as_city = {"_http_status": 200, "active_filters": {"city": "Fort Lauderdale", "zone": None}}
    as_zone = {"_http_status": 200, "active_filters": {"zone": "Fort Lauderdale", "city": "Miami"}}
    elsewhere = {"_http_status": 200, "active_filters": {"city": "Miami", "zone": None}}

    for response, expected in ((as_city, True), (as_zone, True), (elsewhere, False)):
        checks = evaluate_turn(case=case, turn_index=1, turn=turn, response=response, prior_responses=[])
        place_checks = [c for c in checks if c.check_type == "filter_place"]
        assert place_checks and place_checks[0].passed is expected


def test_filter_equals_matches_structured_date_reference_by_expression():
    # active_filters.date_reference is a dict ({expression, resolved_from, ...},
    # S-G6); a plain-string fixture expectation asserts the user's literal token.
    case = _case()
    turn = {
        "message": "Tomorrow 11:00",
        "expect": [{"type": "filter_equals", "values": {"date_reference": "tomorrow"}}],
    }
    response = {
        "_http_status": 200,
        "active_filters": {
            "date_reference": {"expression": "tomorrow", "resolved_from": "relative"}
        },
    }

    checks = evaluate_turn(case=case, turn_index=1, turn=turn, response=response, prior_responses=[])

    equals_checks = [c for c in checks if c.check_type == "filter_equals"]
    assert equals_checks and equals_checks[0].passed


def test_distance_accuracy_rejects_centroid_drift():
    case = _case()
    turn = {
        "message": "Luxury",
        "expect": [{"type": "distance_accuracy", "origin": "native_geolocation"}],
    }
    response = {
        "_http_status": 200,
        "hotels": [
            {
                "name": "Actually far",
                "latitude": 48.9566,
                "longitude": 2.3522,
                "distance_km": 0.7,
            }
        ],
    }

    checks = evaluate_turn(
        case=case,
        turn_index=2,
        turn=turn,
        response=response,
        prior_responses=[{"active_filters": {"city": "Paris"}}],
    )

    assert checks[1].passed is False
    assert "reported=0.7" in checks[1].message


def test_preserve_filter_and_no_repeated_shortlist_checks():
    case = _case()
    turn = {
        "message": "More",
        "expect": [
            {"type": "preserve_filters", "from_turn": 1, "keys": ["city"]},
            {"type": "no_repeated_shortlist", "from_turn": 1},
        ],
    }
    previous = {
        "active_filters": {"city": "Paris"},
        "hotels": [{"id": 1, "name": "A"}],
    }
    current = {
        "_http_status": 200,
        "active_filters": {"city": "Paris"},
        "hotels": [{"id": 2, "name": "B"}],
    }

    checks = evaluate_turn(
        case=case,
        turn_index=2,
        turn=turn,
        response=current,
        prior_responses=[previous],
    )

    assert all(check.passed for check in checks)


def test_duplicate_tool_calls_are_detected_when_adapter_exposes_telemetry():
    case = _case()
    turn = {
        "message": "Near Paris",
        "expect": [{"type": "no_duplicate_tool_calls", "required": True}],
    }
    response = {
        "_http_status": 200,
        "eval_debug": {
            "tool_calls": [
                {"name": "search_hotels", "arguments": {"city": "Paris"}},
                {"name": "search_hotels", "arguments": {"city": "Paris"}},
            ]
        },
    }

    checks = evaluate_turn(
        case=case,
        turn_index=1,
        turn=turn,
        response=response,
        prior_responses=[],
    )

    assert checks[1].passed is False
    assert "search_hotels" in checks[1].message


def test_optional_tool_call_check_passes_when_telemetry_is_unavailable():
    case = _case()
    turn = {
        "message": "Near Paris",
        "expect": [{"type": "no_duplicate_tool_calls", "severity": "warning"}],
    }

    checks = evaluate_turn(
        case=case,
        turn_index=1,
        turn=turn,
        response={"_http_status": 200},
        prior_responses=[],
    )

    assert all(check.passed for check in checks)
    assert "telemetry unavailable" in checks[1].message


def test_compare_reports_classifies_regression_and_improvement():
    baseline = {
        "endpoint": "prod",
        "summary": {"latency_ms": {"p95": 1000}},
        "results": [
            {"id": "a", "suite": "core", "passed": True, "latency_ms": 100},
            {"id": "b", "suite": "core", "passed": False, "latency_ms": 200},
        ],
    }
    candidate = {
        "endpoint": "candidate",
        "summary": {"latency_ms": {"p95": 900}},
        "results": [
            {"id": "a", "suite": "core", "passed": False, "latency_ms": 110},
            {"id": "b", "suite": "core", "passed": True, "latency_ms": 190},
        ],
    }

    report = compare_reports(baseline, candidate)

    assert report["summary"]["regression"] == 1
    assert report["summary"]["improvement"] == 1
    assert report["summary"]["p95_delta_ms"] == -100


def test_load_cases_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "cases.jsonl"
    case = {"id": "same", "turns": [{"message": "x", "expect": []}]}
    path.write_text(json.dumps(case) + "\n" + json.dumps(case) + "\n", encoding="utf-8")

    try:
        load_cases([path])
    except ValueError as exc:
        assert "duplicate case id" in str(exc)
    else:
        raise AssertionError("duplicate ids should fail")
