#!/usr/bin/env python
"""run_release_gate.py — the ship-blocking release gate for the b2c-concierge (S08).

Runs the eval suites against committed baselines and renders a merge / don't-merge
verdict. Adapted from agent-usa `scripts/run_release_gate.py`: the gate is an
ORCHESTRATOR, not a re-implementer — it runs the units, runs the conversational
battery (via run_dynamic_conversation_regression.py), and only owns the
compare-to-baseline + verdict + exit-code logic.

Two modes:
  --quick   units + the per-turn LLM budget invariant (both offline, CI-friendly:
            no OPENAI_API_KEY, no services). The budget cap (<= 3 LLM/turn) is
            enforced inside the units by test_spine.py's budget test.
  (full)    the above + the LIVE 32-scenario conversational battery, judged and
            compared to evals/baselines.json.

Three-tier strictness (agent-usa model):
  - units       : tolerant — a known-failures budget (baselines.units.max_failed).
  - budget      : ZERO tolerance — any turn over 3 LLM calls is ship-blocking.
  - conversation: live-LLM — pass count must stay within `tolerance` of baseline
                  (absorbs run-to-run judge jitter; only DROPS fail the gate).

Exit 0 = green (merge OK). Exit 1 = regression (don't merge). Exit 2 = the gate
could not run (missing creds/report). Baselines are rewritten ONLY with
--update-baseline, and never to make a red run green.

Usage:
  python scripts/run_release_gate.py --quick
  python scripts/run_release_gate.py
  python scripts/run_release_gate.py --update-baseline   # after an INTENTIONAL bar change
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINES_PATH = REPO_ROOT / "evals" / "baselines.json"
REPORTS_DIR = REPO_ROOT / "evals" / "reports"

# Only tolerance knob: the live-LLM battery has +/-1-2 run-to-run jitter, so a
# 1-scenario dip is a rerun, not a rollback (mirrors agent-usa's gate).
CONVERSATION_VARIANCE_TOLERANCE = 2
BATTERY_TIMEOUT_SECONDS = int(os.environ.get("RELEASE_GATE_BATTERY_TIMEOUT_SECONDS", "2400"))


def _load_dotenv() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _load_baselines() -> dict:
    if not BASELINES_PATH.exists():
        print(f"WARN: no baselines at {BASELINES_PATH} — every check will be informational.")
        return {}
    return json.loads(BASELINES_PATH.read_text(encoding="utf-8"))


# --- Suites ---------------------------------------------------------------------------------
_PYTEST_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|error|errors)")


def run_units() -> dict:
    """Run the offline unit suite (pytest testpaths: agents libs evals). Returns
    {passed, failed, line}. The <= 3 LLM/turn budget invariant is covered here
    by test_spine.py's budget test — a 4th call fails a unit."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=1200,
    )
    tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    counts = {kind: int(n) for n, kind in _PYTEST_COUNT_RE.findall(proc.stdout)}
    failed = counts.get("failed", 0) + counts.get("error", 0) + counts.get("errors", 0)
    return {"passed": counts.get("passed", 0), "failed": failed, "line": tail, "exit_code": proc.returncode}


def run_battery(label: str) -> dict | None:
    """Run the live conversational battery via its script; return its parsed
    report, or None if it could not run."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"gate_{label}_conversation.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "run_dynamic_conversation_regression.py"),
            "--output",
            str(report_path),
        ],
        cwd=str(REPO_ROOT),
        env=os.environ,
        timeout=BATTERY_TIMEOUT_SECONDS,
    )
    if proc.returncode != 0 or not report_path.exists():
        print(f"ERROR: battery run failed (exit {proc.returncode}); no verdict possible.")
        return None
    return json.loads(report_path.read_text(encoding="utf-8"))


# --- Verdict --------------------------------------------------------------------------------
def evaluate(units: dict, battery: dict | None, baselines: dict, *, quick: bool) -> list[str]:
    """Return the list of failure strings (empty == green)."""
    failures: list[str] = []

    if (units.get("exit_code", 0) not in (0, 1)
            or (units.get("exit_code") == 1 and units.get("failed", 0) == 0)
            or units.get("passed", 0) + units.get("failed", 0) == 0):
        failures.append("units: suite did not complete or collected no tests")

    base_units = baselines.get("units", {})
    max_failed = base_units.get("max_failed", 0)
    if units["failed"] > max_failed:
        failures.append(
            f"units: {units['failed']} failed > baseline max {max_failed} ({units['line']})"
        )

    if quick:
        return failures
    if battery is None:
        return failures + ["conversation: battery unavailable; full gate cannot pass"]

    summary = battery["summary"]
    base_budget = baselines.get("budget", {})
    cap = base_budget.get("max_llm_calls_per_turn", 3)
    max_over = base_budget.get("max_over_budget_turns", 0)
    # Budget is ZERO tolerance — the structural invariant, never relaxed.
    if summary["over_budget_turns"] > max_over:
        failures.append(
            f"budget (SHIP-BLOCKING): {summary['over_budget_turns']} turn(s) over the "
            f"{cap} LLM/turn cap (baseline allows {max_over})"
        )
    if summary["max_llm_calls_per_turn_observed"] > cap:
        failures.append(
            f"budget (SHIP-BLOCKING): a turn used {summary['max_llm_calls_per_turn_observed']} "
            f"LLM calls > cap {cap}"
        )

    base_conv = baselines.get("conversation", {})
    expected_total = base_conv.get("total")
    if expected_total is None or summary.get("total") != expected_total:
        failures.append(
            f"conversation coverage: {summary.get('total')} cases, expected {expected_total}; recalibrate explicitly"
        )
    for family, expected in base_conv.get("by_family", {}).items():
        actual = summary.get("by_family", {}).get(family, {}).get("count")
        if actual != expected.get("count"):
            failures.append(f"conversation coverage: family {family} has {actual} cases, expected {expected.get('count')}")
    min_passed = base_conv.get("min_passed")
    tolerance = base_conv.get("tolerance", CONVERSATION_VARIANCE_TOLERANCE)
    if min_passed is not None and summary["passed"] < min_passed - tolerance:
        failures.append(
            f"conversation: {summary['passed']} passed < baseline min "
            f"{min_passed} - tolerance {tolerance} = {min_passed - tolerance}"
        )
    return failures


def baseline_refusal(units: dict, battery: dict | None) -> str | None:
    """Why this run must not become the baseline, or None. A judge `error`
    (e.g. a provider 400 on a new judge model) reads as a plain fail in the
    pass count, and `max_failed` is copied from this run's unit failures."""
    errors = (battery or {}).get("summary", {}).get("errors", 0)
    if errors:
        return f"{errors} judge error(s) in this run: fix the judge before recording a baseline"
    if units.get("failed", 0):
        return f"{units['failed']} unit failure(s): a baseline must not absorb them"
    return None


def judge_mismatch(battery: dict | None, baselines: dict) -> str | None:
    """A warning when this run and the baseline were graded by different judges:
    the pass counts are then not comparable, whatever the verdict says."""
    recorded = baselines.get("conversation", {}).get("judge_model")
    current = (battery or {}).get("judge_model")
    if recorded and current and recorded != current:
        return (f"baseline judged by {recorded}, this run by {current}: pass counts are not "
                "comparable — refresh the baseline with --update-baseline")
    return None


def write_baselines(units: dict, battery: dict | None, label: str, prior: dict) -> None:
    """Rewrite baselines.json from this run. Budget maxes are HARDCODED to the
    invariant (cap 3, zero over-budget turns) — never auto-relaxed. Conversation
    min_passed = this run's pass count (the new floor)."""
    summary = battery["summary"] if battery else {}
    prior_conv = prior.get("conversation", {})
    baselines = {
        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "updated_by_label": label,
        "note": (
            "Baselines for the b2c-concierge release gate (S08). Update ONLY via "
            "run_release_gate.py --update-baseline, on an INTENTIONAL bar change — "
            "never to make a red run green. Budget is a structural invariant and is "
            "never relaxed here."
        ),
        "units": {
            "max_failed": units["failed"],
            "note": "Gate fails if the offline unit suite has MORE failures than this.",
        },
        "budget": {
            "max_llm_calls_per_turn": 3,
            "max_over_budget_turns": 0,
            "note": "ZERO tolerance: any turn over 3 LLM calls is ship-blocking (CLAUDE.md invariant).",
        },
        "conversation": {
            "min_passed": summary.get("passed", prior_conv.get("min_passed", 0)),
            "total": summary.get("total", prior_conv.get("total", 32)),
            "tolerance": prior_conv.get("tolerance", CONVERSATION_VARIANCE_TOLERANCE),
            "judge_model": (battery or {}).get("judge_model", prior_conv.get("judge_model", "")),
            "by_family": {
                fam: {"passed": stat["passed"], "count": stat["count"]}
                for fam, stat in summary.get("by_family", {}).items()
            },
            "note": (
                "Live-LLM battery: min_passed is a floor; the gate fails only if a run "
                "drops below min_passed - tolerance. by_family is informational."
            ),
        },
    }
    BASELINES_PATH.write_text(json.dumps(baselines, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"baselines rewritten → {BASELINES_PATH} (label={label})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="units + budget only (offline).")
    parser.add_argument("--skip-units", action="store_true", help="Skip the pytest units.")
    parser.add_argument(
        "--label", default=datetime.datetime.now().strftime("%Y%m%d_%H%M"), help="Tags output files."
    )
    parser.add_argument(
        "--update-baseline", action="store_true", help="Rewrite baselines.json from this run."
    )
    args = parser.parse_args()
    _load_dotenv()
    baselines = _load_baselines()

    print(f"release gate ({'quick' if args.quick else 'full'}) — label={args.label}\n")

    units = {"passed": 0, "failed": 0, "line": "(skipped)"}
    if not args.skip_units:
        print("• units …", flush=True)
        units = run_units()
        print(f"  units: {units['line']}")

    battery = None
    if not args.quick:
        if not os.environ.get("OPENAI_API_KEY"):
            print(
                "\nERROR: the full gate needs OPENAI_API_KEY (triage/synthesis/judge) and the "
                "leaves booted (bash scripts/run_local.sh). Use --quick for the offline gate."
            )
            return 2
        print("\n• conversational battery (live) …", flush=True)
        battery = run_battery(args.label)
        if battery is None:
            return 2
        s = battery["summary"]
        print(
            f"  battery: {s['passed']}/{s['total']} passed · "
            f"{s.get('errors', 0)} judge error(s) · "
            f"budget max {s['max_llm_calls_per_turn_observed']}/turn · "
            f"{s['over_budget_turns']} over-budget"
        )
        mismatch = judge_mismatch(battery, baselines)
        if mismatch:
            print(f"  ⚠ {mismatch}")

    failures = evaluate(units, battery, baselines, quick=args.quick)

    if args.update_baseline:
        refusal = baseline_refusal(units, battery)
        if refusal:
            print(f"\nERROR: baseline NOT rewritten — {refusal}.")
            return 2
        write_baselines(units, battery, args.label, baselines)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    verdict = "PASS" if not failures else "FAIL"
    (REPORTS_DIR / f"release_gate_{args.label}.json").write_text(
        json.dumps(
            {
                "label": args.label,
                "mode": "quick" if args.quick else "full",
                "verdict": verdict,
                "failures": failures,
                "units": units,
                "battery_summary": battery["summary"] if battery else None,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"\n{'='*56}")
    if failures:
        print(f"RELEASE GATE: FAIL — DON'T MERGE ({len(failures)} issue(s))")
        for f in failures:
            print(f"  ✗ {f}")
    else:
        print("RELEASE GATE: PASS — no regression vs baseline")
    print("=" * 56)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
