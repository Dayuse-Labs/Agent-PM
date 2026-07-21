"""Compare a candidate eval run with a frozen baseline run."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _index(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row["id"]): row
        for row in report.get("results") or []
        if isinstance(row, dict) and row.get("id")
    }


def compare_reports(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    before = _index(baseline)
    after = _index(candidate)
    rows: list[dict[str, Any]] = []
    for case_id in sorted(set(before) | set(after)):
        old = before.get(case_id)
        new = after.get(case_id)
        if old is None:
            classification = "new_case"
        elif new is None:
            classification = "missing_case"
        elif old.get("passed") and not new.get("passed"):
            classification = "regression"
        elif not old.get("passed") and new.get("passed"):
            classification = "improvement"
        elif new.get("passed"):
            classification = "unchanged_pass"
        else:
            classification = "unchanged_fail"
        old_latency = float((old or {}).get("latency_ms") or 0)
        new_latency = float((new or {}).get("latency_ms") or 0)
        rows.append(
            {
                "id": case_id,
                "suite": (new or old or {}).get("suite"),
                "classification": classification,
                "baseline_passed": (old or {}).get("passed"),
                "candidate_passed": (new or {}).get("passed"),
                "baseline_latency_ms": old_latency or None,
                "candidate_latency_ms": new_latency or None,
                "latency_delta_ms": round(new_latency - old_latency, 2)
                if old_latency and new_latency
                else None,
            }
        )
    counts = Counter(row["classification"] for row in rows)
    baseline_latency = float((baseline.get("summary") or {}).get("latency_ms", {}).get("p95") or 0)
    candidate_latency = float(
        (candidate.get("summary") or {}).get("latency_ms", {}).get("p95") or 0
    )
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "baseline_endpoint": baseline.get("endpoint"),
        "candidate_endpoint": candidate.get("endpoint"),
        "summary": {
            **dict(counts),
            "total_compared": len(rows),
            "baseline_p95_ms": baseline_latency,
            "candidate_p95_ms": candidate_latency,
            "p95_delta_ms": round(candidate_latency - baseline_latency, 2),
        },
        "cases": rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", default="eval_pack/results/comparison.json")
    parser.add_argument("--allow-regressions", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    report = compare_reports(baseline, candidate)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = report["summary"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report: {output}")
    if summary.get("regression", 0) and not args.allow_regressions:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
