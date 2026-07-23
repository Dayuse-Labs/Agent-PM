#!/usr/bin/env python3
"""eval_replay_stability.py — S-G8 item 8: replay the 81 critical gate cases
(geo + multiturn + prod_wounds — 41 + 27 + 13, the exact set REVIEW-GEO-
MULTITURN-AGENTB2C-2026-07-22.md calls "parité sur les 81 cas geo/multi-turn/
blessures production") at least 3x, and report per-case pass/fail VARIANCE —
LLM-driven runs are not bit-reproducible, so a single run cannot tell a real
regression from run-to-run jitter (HANDOFF S-G4: gpt-5.2 canary already showed
~2x latency swings on the same case).

This is preparation for the S-G9 gate — it measures stability, it does not
decide merge/no-merge (that verdict logic is explicitly OUT of S-G8's scope).

The pack (`dayuse_eval_pack/eval_pack/**`) is never modified: this only
shells out to the untouched `python -m eval_pack.runner`, N times, and
diffs the resulting reports.

Usage:
    python3 -u scripts/eval_replay_stability.py \\
        --endpoint http://127.0.0.1:8100/v3/chat \\
        --output-dir /path/to/scratch/replay \\
        --runs 3
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_PACK_DIR = REPO_ROOT / "dayuse_eval_pack"
CASES_DIR = EVAL_PACK_DIR / "eval_pack" / "cases"
CRITICAL_SUITES = ("geo", "multiturn", "prod_wounds")


def critical_suite_case_ids(cases_dir: Path = CASES_DIR) -> list[str]:
    """The 81-case critical gate set, read straight from the fixtures (never
    hand-picked) — every id in the geo/multiturn/prod_wounds suite files."""
    ids: list[str] = []
    for suite in CRITICAL_SUITES:
        path = cases_dir / f"{suite}.jsonl"
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    ids.append(str(json.loads(line)["id"]))
    return ids


# --- pure stability computation (unit-tested directly on synthetic reports) --
def compute_stability(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """`reports` = N parsed run-report dicts, each shaped like
    `eval_pack.runner.build_report`'s output (`{summary, results:[{id, suite,
    passed, latency_ms, ...}]}`). A case is "stable" iff every run agrees on
    pass/fail. Cases missing from some runs (e.g. a run crashed mid-way) are
    reported separately, never silently treated as a pass or a fail."""
    n_runs = len(reports)
    per_case: dict[str, dict[str, Any]] = {}
    for run_index, report in enumerate(reports):
        for row in report.get("results") or []:
            case_id = str(row.get("id"))
            entry = per_case.setdefault(
                case_id, {"suite": row.get("suite"), "outcomes": [None] * n_runs}
            )
            entry["outcomes"][run_index] = bool(row.get("passed"))

    incomplete = sorted(cid for cid, entry in per_case.items() if None in entry["outcomes"])
    complete = {cid: entry for cid, entry in per_case.items() if cid not in incomplete}

    unstable = []
    for case_id, entry in complete.items():
        outcomes = entry["outcomes"]
        pass_count = sum(1 for o in outcomes if o)
        entry["pass_count"] = pass_count
        entry["stable"] = pass_count in (0, n_runs)
        if not entry["stable"]:
            unstable.append(case_id)
    unstable.sort()

    by_suite: dict[str, dict[str, int]] = {}
    for case_id, entry in complete.items():
        row = by_suite.setdefault(str(entry["suite"]), {"total": 0, "unstable": 0})
        row["total"] += 1
        if not entry["stable"]:
            row["unstable"] += 1

    stable_count = len(complete) - len(unstable)
    return {
        "n_runs": n_runs,
        "total_cases": len(per_case),
        "complete_cases": len(complete),
        "incomplete_case_ids": incomplete,
        "unstable_case_ids": unstable,
        "stability_rate": round(stable_count / len(complete), 4) if complete else 0.0,
        "by_suite": by_suite,
        "per_case": per_case,
    }


# --- thin subprocess orchestration --------------------------------------------
RunnerInvoker = Callable[[str, list[str], Path, str, int], Path]


def invoke_runner_subprocess(
    endpoint: str, case_ids: list[str], output_path: Path, api_key: str = "", timeout: int = 120
) -> Path:
    """One `python -u -m eval_pack.runner` call, cwd'd into `dayuse_eval_pack`
    (its own package root — mirrors run_release_gate.py's subprocess style).
    `-u` avoids the buffered-stdout trap documented in HANDOFF S-A for
    detached/long-running runners."""
    args = [
        sys.executable,
        "-u",
        "-m",
        "eval_pack.runner",
        "--endpoint",
        endpoint,
        "--ids",
        ",".join(case_ids),
        "--timeout",
        str(timeout),
        "--allow-failures",
        "--output",
        str(output_path),
    ]
    if api_key:
        args += ["--api-key", api_key]
    subprocess.run(args, cwd=str(EVAL_PACK_DIR), check=True)
    return output_path


def replay(
    *,
    endpoint: str,
    output_dir: Path,
    runs: int = 3,
    case_ids: list[str] | None = None,
    api_key: str = "",
    timeout: int = 120,
    invoker: RunnerInvoker = invoke_runner_subprocess,
) -> dict[str, Any]:
    ids = case_ids if case_ids is not None else critical_suite_case_ids()
    output_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for run_index in range(runs):
        run_path = output_dir / f"replay_{run_index + 1}.json"
        invoker(endpoint, ids, run_path, api_key, timeout)
        reports.append(json.loads(run_path.read_text(encoding="utf-8")))
    return compute_stability(reports)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--output-dir", required=True, help="Where the N raw replay reports + the stability report land")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--timeout", type=int, default=120)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    stability = replay(
        endpoint=args.endpoint,
        output_dir=output_dir,
        runs=args.runs,
        api_key=args.api_key,
        timeout=args.timeout,
    )
    stability_path = output_dir / "stability_report.json"
    stability_path.write_text(json.dumps(stability, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"stability: {stability['stability_rate']:.1%} "
        f"({stability['complete_cases'] - len(stability['unstable_case_ids'])}/{stability['complete_cases']} stable, "
        f"{len(stability['incomplete_case_ids'])} incomplete)"
    )
    if stability["unstable_case_ids"]:
        print(f"unstable: {stability['unstable_case_ids']}")
    print(f"Report: {stability_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
