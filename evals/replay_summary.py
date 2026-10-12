"""Aggregate replay coverage and observed KPIs without exporting conversation text.

Completion means transport completion, NOT answer correctness. Conversion/CTR
cannot be inferred from counterfactual model replies. Costs use the application's
existing LiteLLM estimates, not invoices. Missing metric coverage is explicit.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evals.production_corpus import atomic_json


def distribution(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "p50": None, "p95": None}
    values = sorted(values)
    return {"n": len(values), "mean": round(sum(values) / len(values), 3),
            "p50": values[math.ceil(len(values) * .5) - 1], "p95": values[math.ceil(len(values) * .95) - 1]}


def retained_metrics(cases: list[dict], metrics: list[dict], variant: str) -> list[dict]:
    """Join only the retained attempt; older instrumentation is never guessed on resume."""
    keys = {(case["case_id"], str(turn["index"])) for case in cases for turn in case["turns"]}
    sessions = {case["case_id"]: case["session_id"] for case in cases}
    resumed = {case["case_id"] for case in cases if case.get("previous_sessions")}
    return [m for m in metrics if m.get("x-replay-variant") == variant
              and (m.get("x-replay-case"), m.get("x-replay-turn")) in keys
              and ((m.get("x-replay-session-id") == sessions.get(m.get("x-replay-case")))
                   if m.get("x-replay-session-id") else m.get("x-replay-case") not in resumed)]


def summarize(directory: Path, metrics: list[dict]) -> dict[str, Any]:
    manifest = json.loads((directory / "manifest.json").read_text())
    variant = manifest["identity"]["variant"]
    cases = [json.loads(p.read_text()) for p in (directory / "cases").glob("*.json")]
    turns = [(case, turn) for case in cases for turn in case["turns"]]
    resumed = {case["case_id"] for case in cases if case.get("previous_sessions")}
    joined = retained_metrics(cases, metrics, variant)
    turn_metrics = [m for m in joined if m["event_type"] == "turn"]
    llm = [m for m in joined if m["event_type"] == "llm_call"]
    all_attempt_llm = [m for m in metrics if m.get("x-replay-variant") == variant and m["event_type"] == "llm_call"]
    calls: Counter = Counter((m["x-replay-case"], m["x-replay-turn"]) for m in llm)
    timing: dict[str, list] = defaultdict(list)
    for _, turn in turns:
        for key, value in turn["timing_ms"].items():
            timing[key].append(value)
    invalid = (directory / "INVALIDATED.json").exists()
    result_turns = sum(bool(t["response"].get("hotels")) for _, t in turns)
    eur_on_empty = sum(not t["response"].get("hotels") and any(
        phrase in t["response"].get("message", "") for phrase in
        ("Prices are shown in EUR", "Prix affichés en euros, sans conversion")) for _, t in turns)
    return {
        "variant": variant, "manifest_complete": manifest.get("complete", False), "invalidated": invalid,
        "expected_sessions": manifest.get("expected_sessions"), "expected_turns": manifest.get("expected_turns"),
        "completed_sessions": sum(bool(c["complete"]) for c in cases), "attempted_sessions": len(cases),
        "completed_turns": len(turns), "sessions_with_errors": sum("error" in c for c in cases),
        "traffic_sessions": dict(Counter(c["traffic"] for c in cases)),
        "result_turns": result_turns, "eur_disclosure_without_cards": eur_on_empty,
        "latency_ms": {k: distribution(v) for k, v in timing.items()},
        "measured_turn_events": len(turn_metrics), "turn_statuses": dict(Counter(m.get("status") for m in turn_metrics)),
        "resumed_sessions": len(resumed),
        "turn_families": dict(Counter(m.get("family") for m in turn_metrics)),
        "actual_llm_call_events": len(llm), "actual_calls_on_turns_with_llm": distribution(list(calls.values())),
        "logical_budget_calls": distribution([m["llm_calls"] for m in turn_metrics if "llm_calls" in m]),
        "llm_error_events": sum(m.get("status") != "ok" for m in llm),
        "estimated_cost_usd": round(sum(m.get("cost_usd") or 0 for m in llm), 6),
        "all_attempts_estimated_cost_usd": round(sum(m.get("cost_usd") or 0 for m in all_attempt_llm), 6),
        "llm_events_without_cost": sum(m.get("cost_usd") is None for m in llm),
        "policy_accuracy": "not_graded_by_this_report",
        "ctr_and_conversion": "not_measurable_offline",
        "limitations": ["Historical user continuations may depend on old assistant replies.",
                        "Browser GPS, timezone and booking context were not captured by the source logs.",
                        "Current shared inventory is not historical availability.",
                        "Latency includes local replay load and fixture acquisition; not production latency.",
                        "Only metrics joined to the retained attempt are counted; earlier attempts cost extra.",
                        "Resumed sessions with pre-session-ID instrumentation have missing old metric coverage, not zero cost."]}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--metrics", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    metrics = []
    for path in args.metrics.glob("*.jsonl"):
        snapshot = path.read_text()
        lines = snapshot.splitlines()
        for index, line in enumerate(lines):
            try:
                metrics.append(json.loads(line))
            except json.JSONDecodeError:
                # A live process may be in the middle of its final append.
                if index != len(lines) - 1 or snapshot.endswith("\n"):
                    raise
    result = summarize(args.run, metrics)
    atomic_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
