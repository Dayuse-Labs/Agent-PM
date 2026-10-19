"""Offline tests for the release gate's verdict logic (no subprocess, no LLM).

Loads scripts/run_release_gate.py by path (it is a script, not a package) and
exercises `evaluate` — the compare-to-baseline heart of the gate.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_GATE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_release_gate.py"
_spec = importlib.util.spec_from_file_location("run_release_gate", _GATE_PATH)
gate = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(gate)


BASELINES = {
    "units": {"max_failed": 0},
    "budget": {"max_llm_calls_per_turn": 3, "max_over_budget_turns": 0},
    "conversation": {"min_passed": 20, "total": 32, "tolerance": 2},
}


def _battery(passed=25, over_budget=0, max_calls=3):
    return {
        "summary": {
            "passed": passed,
            "total": 32,
            "over_budget_turns": over_budget,
            "max_llm_calls_per_turn_observed": max_calls,
        }
    }


def test_green_when_within_baseline():
    units = {"passed": 300, "failed": 0, "line": "300 passed"}
    assert gate.evaluate(units, _battery(), BASELINES, quick=False) == []


def test_units_regression_fails():
    units = {"passed": 299, "failed": 1, "line": "299 passed, 1 failed"}
    failures = gate.evaluate(units, _battery(), BASELINES, quick=False)
    assert any("units" in f for f in failures)


def test_over_budget_is_ship_blocking():
    units = {"passed": 300, "failed": 0, "line": "ok"}
    failures = gate.evaluate(units, _battery(over_budget=1, max_calls=4), BASELINES, quick=False)
    assert any("SHIP-BLOCKING" in f for f in failures)


def test_conversation_drop_beyond_tolerance_fails():
    units = {"passed": 300, "failed": 0, "line": "ok"}
    # min_passed 20, tolerance 2 → floor 18; 17 passed must fail.
    failures = gate.evaluate(units, _battery(passed=17), BASELINES, quick=False)
    assert any("conversation" in f for f in failures)


def test_conversation_dip_within_tolerance_is_green():
    units = {"passed": 300, "failed": 0, "line": "ok"}
    # 18 passed == floor (20 - 2) → not below → green.
    assert gate.evaluate(units, _battery(passed=18), BASELINES, quick=False) == []


def test_quick_mode_skips_battery_checks():
    units = {"passed": 300, "failed": 0, "line": "ok"}
    # Even a wildly over-budget battery is ignored in quick mode (battery not run).
    assert gate.evaluate(units, None, BASELINES, quick=True) == []


def test_quick_mode_still_checks_units():
    units = {"passed": 1, "failed": 5, "line": "5 failed"}
    assert gate.evaluate(units, None, BASELINES, quick=True)


def test_truncated_battery_does_not_pass_even_when_pass_count_is_high():
    report = _battery(passed=25)
    report["summary"]["total"] = 25
    assert gate.evaluate({"passed": 300, "failed": 0, "line": "ok"}, report, BASELINES, quick=False)


def test_full_gate_needs_battery_and_quick_gate_needs_real_tests():
    units = {"passed": 300, "failed": 0, "line": "ok"}
    assert gate.evaluate(units, None, BASELINES, quick=False)
    assert gate.evaluate({"passed": 0, "failed": 0, "line": "interrupted", "exit_code": 2}, None, BASELINES, quick=True)


def test_missing_family_coverage_fails():
    baseline = {**BASELINES, "conversation": {**BASELINES["conversation"], "by_family": {"faq": {"count": 4}}}}
    assert gate.evaluate({"passed": 300, "failed": 0, "line": "ok"}, _battery(), baseline, quick=False)


def test_a_run_with_judge_errors_never_becomes_the_baseline():
    units = {"passed": 300, "failed": 0, "line": "ok"}
    battery = _battery()
    assert gate.baseline_refusal(units, battery) is None
    battery["summary"]["errors"] = 2
    assert "judge error" in gate.baseline_refusal(units, battery)
    assert "unit failure" in gate.baseline_refusal({"failed": 1}, _battery())
    unhealthy = _battery()
    unhealthy["summary"]["degraded_turns"] = 112
    assert "degraded" in gate.baseline_refusal(units, unhealthy)


def test_a_judge_change_is_flagged():
    battery = {**_battery(), "judge_model": "openai/gpt-6-luna"}
    assert gate.judge_mismatch(battery, BASELINES) is None  # no recorded judge
    recorded = {"conversation": {"judge_model": "gpt-4o-mini"}}
    assert "gpt-4o-mini" in gate.judge_mismatch(battery, recorded)
    same = {"conversation": {"judge_model": "openai/gpt-6-luna"}}
    assert gate.judge_mismatch(battery, same) is None
