"""Compare the same complete conversations, with explicit corpus and metric coverage.

No assistant text is exported. This reports observations, not answer correctness,
conversion uplift, historical inventory accuracy or a release authorization.
Exit 2 means the corpus comparison is incomplete; partial aggregates are descriptive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from evals.production_corpus import atomic_json
from evals.production_replay import compile_cases, digest
from evals.replay_summary import distribution, retained_metrics


def load_run(directory: Path, expected: list[dict], corpus_sha: str) -> tuple[dict, dict]:
    if (directory / "INVALIDATED.json").exists() or (directory / "SUPERSEDED.json").exists():
        raise ValueError("invalidated or superseded run is not a final comparison candidate")
    manifest = json.loads((directory / "manifest.json").read_text())
    identity = manifest["identity"]
    if identity["provenance"]["corpus_sha256"] != corpus_sha or identity["cases_hash"] != digest(expected):
        raise ValueError("run does not match the supplied corpus and selected inputs")
    by_id = {c["id"]: c for c in expected}
    cases = {}
    for file in (directory / "cases").glob("*.json"):
        case = json.loads(file.read_text())
        cid = case["case_id"]
        if cid in cases or cid not in by_id or case["input_hash"] != digest(by_id[cid]):
            raise ValueError("duplicate, unknown or modified conversation checkpoint")
        source = by_id[cid]
        if case["complete"] and case.get("error"):
            raise ValueError("complete checkpoint still contains an error")
        if any(case[k] != source[k] for k in ("split", "traffic")):
            raise ValueError("checkpoint population differs from source inputs")
        turns = case["turns"]
        if len(turns) > len(source["turns"]) or (case["complete"] and len(turns) != len(source["turns"])):
            raise ValueError("checkpoint turn count contradicts source inputs")
        for index, (turn, original) in enumerate(zip(turns, source["turns"]), 1):
            if turn["index"] != index or turn["row_id"] != original["row_id"]:
                raise ValueError("checkpoint turn identity/order differs from source inputs")
            if not isinstance(turn.get("response", {}).get("message"), str):
                raise ValueError("checkpoint lacks a final response")
        cases[cid] = case
    if not expected:
        raise ValueError("an empty cohort is not an evaluation")
    return manifest, cases


def observations(cases: list[dict], metrics: list[dict], variant: str) -> dict:
    turns = [(c, t) for c in cases for t in c["turns"]]
    joined = retained_metrics(cases, metrics, variant)
    llm = [m for m in joined if m["event_type"] == "llm_call"]
    llm_turns = {(m["x-replay-case"], int(m["x-replay-turn"])) for m in llm}
    events = defaultdict(list)
    for m in joined:
        if m["event_type"] == "turn":
            events[(m["x-replay-case"], int(m["x-replay-turn"]))].append(m)
    valid_events = {k: v[0] for k, v in events.items() if len(v) == 1}
    flags = {}
    for c, t in turns:
        key = (c["case_id"], t["index"])
        cards = bool(t["response"].get("hotels"))
        text = t["response"]["message"]
        flags[key] = {
            "has_results": cards,
            "eur_disclosure_without_cards": not cards and any(s in text for s in
                ("Prices are shown in EUR", "Prix affichés en euros, sans conversion")),
            "non_ok_turn_status": valid_events[key].get("status") != "ok" if key in valid_events else None,
        }
    return {
        "summary": {
            "sessions": len(cases), "turns": len(turns),
            "unique_turn_metric_coverage": len(valid_events),
            "turns_missing_or_duplicating_metrics": len(turns) - len(valid_events),
            "actual_llm_call_events": len(llm),
            "turns_with_observed_llm_events": len(llm_turns),
            "observed_estimated_cost_usd": round(sum(m.get("cost_usd") or 0 for m in llm), 6),
            "llm_events_without_cost": sum(m.get("cost_usd") is None for m in llm),
            "logical_budget_calls": distribution([m["llm_calls"] for m in valid_events.values() if "llm_calls" in m]),
            "local_total_latency_ms": distribution([t["timing_ms"]["total"] for _, t in turns]),
            "flags": {name: sum(v[name] is True for v in flags.values()) for name in
                      ("has_results", "eur_disclosure_without_cards", "non_ok_turn_status")},
        },
        "flags": flags,
    }


def compare(baseline: Path, candidate: Path, expected: list[dict], corpus_sha: str, metrics: list[dict]) -> dict:
    bm, bc = load_run(baseline, expected, corpus_sha)
    cm, cc = load_run(candidate, expected, corpus_sha)
    for key in ("model", "inventory_day", "split", "limit", "naive_log_timezone", "inventory"):
        if bm["identity"]["provenance"].get(key) != cm["identity"]["provenance"].get(key):
            raise ValueError(f"incomparable run provenance: {key}")
    if bm["identity"]["concurrency"] != cm["identity"]["concurrency"]:
        raise ValueError("incomparable configured concurrency")
    paired = {cid for cid in bc.keys() & cc.keys() if bc[cid]["complete"] and cc[cid]["complete"]}
    complete = bool(bm.get("complete") and cm.get("complete") and len(paired) == len(expected))
    groups = {"all": paired}
    for field in ("split", "traffic"):
        for value in sorted({c[field] for c in expected}):
            groups[f"{field}:{value}"] = {cid for cid in paired if bc[cid][field] == value}
    cohorts = {}
    for name, ids in groups.items():
        bo = observations([bc[cid] for cid in sorted(ids)], metrics, bm["identity"]["variant"])
        co = observations([cc[cid] for cid in sorted(ids)], metrics, cm["identity"]["variant"])
        transitions = {}
        for flag in ("has_results", "eur_disclosure_without_cards", "non_ok_turn_status"):
            counts: Counter = Counter()
            for key, b in bo["flags"].items():
                c = co["flags"][key]
                label = "unscored_metric_coverage" if b[flag] is None or c[flag] is None else f"{int(b[flag])}->{int(c[flag])}"
                counts[label] += 1
            transitions[flag] = dict(counts)
        cohorts[name] = {"baseline": bo["summary"], "candidate": co["summary"], "paired_flag_transitions": transitions}
    return {
        "version": 1, "comparison_complete": complete, "release_approved": False,
        "corpus_sha256": corpus_sha,
        "revisions": {"baseline": bm["identity"]["provenance"]["code_sha"], "candidate": cm["identity"]["provenance"]["code_sha"]},
        "coverage": {"expected_sessions": len(expected), "expected_turns": sum(len(c["turns"]) for c in expected),
                     "baseline_complete_sessions": sum(c["complete"] for c in bc.values()),
                     "candidate_complete_sessions": sum(c["complete"] for c in cc.values()),
                     "paired_complete_sessions": len(paired), "unpaired_sessions": len(expected) - len(paired)},
        "paired_cohorts": cohorts,
        "policy_accuracy": "not_graded", "ctr_and_conversion": "not_measurable_offline",
        "limitations": ["Only the same complete conversations contribute to paired measures.",
                        "Partial coverage may be selection-biased and is not a full-corpus result.",
                        "Result presence and transport completion do not establish correctness.",
                        "The EUR flag recognizes the application's two stock disclosure templates, not all model paraphrases.",
                        "LLM cost covers observed retained-attempt events; missing events are not zero cost.",
                        "Local latency depends on cache acquisition and machine load; not causal production latency.",
                        "Historical user continuations may depend on the recorded old replies.",
                        "An untouched holdout split label does not make ungraded outcomes a quality score."]}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("baseline", "candidate", "corpus", "metrics", "output"):
        p.add_argument(f"--{key}", type=Path, required=True)
    args = p.parse_args()
    raw = args.corpus.read_bytes()
    cases, _ = compile_cases([json.loads(line) for line in raw.splitlines()])
    provenance = json.loads((args.baseline / "manifest.json").read_text())["identity"]["provenance"]
    if provenance.get("split"):
        cases = [c for c in cases if c["split"] == provenance["split"]]
    if provenance.get("limit"):
        cases = sorted(cases, key=lambda c: (c["family_hint"] != "faq_or_booking", c["id"]))[:provenance["limit"]]
    metrics = []
    for file in args.metrics.glob("*.jsonl"):
        snapshot = file.read_text()
        lines = snapshot.splitlines()
        for i, line in enumerate(lines):
            try:
                metrics.append(json.loads(line))
            except json.JSONDecodeError:
                if i != len(lines) - 1 or snapshot.endswith("\n"):
                    raise
    result = compare(args.baseline, args.candidate, cases, hashlib.sha256(raw).hexdigest(), metrics)
    atomic_json(args.output, result)
    print(json.dumps({"comparison_complete": result["comparison_complete"], **result["coverage"]}))
    raise SystemExit(0 if result["comparison_complete"] else 2)


if __name__ == "__main__":
    main()
