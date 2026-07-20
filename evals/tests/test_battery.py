"""Offline tests for the battery harness helpers (no runner, no LLM, no network).

The live in-process driving is exercised by the release gate, not here — these
lock the pure logic: scenario loading, per-turn budget parsing/capture, and the
per-family + budget aggregation the gate reads.
"""
from __future__ import annotations

import logging

from evals import battery
from evals.battery import (
    FAMILY_ORDER,
    MAX_LLM_CALLS_PER_TURN,
    TurnMetricHandler,
    _scenario_result,
    load_scenarios,
    parse_turn_metric,
    summarize,
)
from evals.judge import Judgment


def test_load_scenarios_all():
    scenarios = load_scenarios()
    assert len(scenarios) == 32
    families = {s["family"] for s in scenarios}
    assert families == set(FAMILY_ORDER)


def test_load_scenarios_family_filter_and_limit():
    scenarios = load_scenarios(families=["compare", "simple_search"], limit=1)
    assert len(scenarios) == 2
    assert {s["family"] for s in scenarios} == {"compare", "simple_search"}


def test_load_scenarios_family_order():
    scenarios = load_scenarios(limit=1)
    assert [s["family"] for s in scenarios] == list(FAMILY_ORDER)


def test_parse_turn_metric_matches_real_line():
    line = (
        "concierge_metric=turn family=search route=leaf:hotel_search "
        "llm_calls=3 phases=triage,leaf_llm,synthesis ms=8421 status=ok"
    )
    m = parse_turn_metric(line)
    assert m == {
        "family": "search",
        "route": "leaf:hotel_search",
        "llm_calls": 3,
        "phases": "triage,leaf_llm,synthesis",
        "ms": 8421,
        "status": "ok",
    }


def test_parse_turn_metric_ignores_other_lines():
    assert parse_turn_metric("concierge_metric=leaf_call leaf=faq ms=12 status=ok") is None
    assert parse_turn_metric("some unrelated log") is None


def test_turn_metric_handler_captures_and_drains():
    logger = logging.getLogger("test.metrics.capture")
    handler = TurnMetricHandler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info(
        "concierge_metric=turn family=ack route=template:ack llm_calls=0 phases=- ms=3 status=ok"
    )
    logger.info("concierge_metric=leaf_call leaf=x ms=1 status=ok")  # ignored
    drained = handler.drain()
    assert len(drained) == 1 and drained[0]["family"] == "ack" and drained[0]["llm_calls"] == 0
    assert handler.drain() == []  # drained clears


def _result(family: str, verdict: str, max_calls: int) -> dict:
    turns = [{"user": "u", "answer": "a", "llm_calls": max_calls, "phases": "", "route": "", "status": "ok"}]
    return _scenario_result(
        {"id": f"{family}-x", "family": family, "lang": "fr", "user_turns": ["u"]},
        turns,
        Judgment(f"{family}-x", family, verdict, 5.0 if verdict == "pass" else 1.0, "why"),
    )


def test_scenario_result_flags_over_budget():
    ok = _result("search", "pass", MAX_LLM_CALLS_PER_TURN)
    assert ok["over_budget"] is False and ok["max_llm_calls"] == MAX_LLM_CALLS_PER_TURN
    bad = _result("search", "pass", MAX_LLM_CALLS_PER_TURN + 1)
    assert bad["over_budget"] is True


def test_summarize_aggregates_families_and_budget():
    results = [
        _result("simple_search", "pass", 3),
        _result("simple_search", "fail", 3),
        _result("compare", "pass", 2),
        _result("compare", "pass", 4),  # over budget
    ]
    summary = summarize(results)
    assert summary["total"] == 4
    assert summary["passed"] == 3
    assert summary["failed"] == 1
    assert summary["over_budget_turns"] == 1
    assert summary["max_llm_calls_per_turn_observed"] == 4
    assert summary["by_family"]["simple_search"] == {"passed": 1, "count": 2, "pass_rate": 0.5}
    assert summary["by_family"]["compare"]["passed"] == 2
    # canonical order preserved
    assert list(summary["by_family"].keys()) == ["simple_search", "compare"]


def test_max_llm_calls_mirrors_spine_invariant():
    # Guards against silent drift from the CLAUDE.md "<= 3 LLM/turn" invariant.
    from b2c_concierge.budget import MAX_LLM_CALLS_PER_TURN as spine_cap

    assert battery.MAX_LLM_CALLS_PER_TURN == spine_cap == 3
