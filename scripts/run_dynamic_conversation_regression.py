#!/usr/bin/env python
"""run_dynamic_conversation_regression.py — the live conversational battery (S08).

Replays the 32-scenario evalset (8 families x 4) through the b2c-concierge
IN-PROCESS (see evals/battery.py for why in-process, not HTTP) and judges each
scenario with the LLM-as-judge. Writes a JSON report and prints per-family pass
rates + the per-turn LLM-budget accounting. Produces a REPORT only — the
merge / don't-merge verdict is `scripts/run_release_gate.py`'s job.

LIVE dependencies (this is the "batterie live"):
  - OPENAI_API_KEY (triage + synthesis + judge) — loaded from .env if present;
  - the search + faq A2A leaves booted (bash scripts/run_local.sh) for the
    search/faq/empty*/budget/timeslot families — a leaf that is down degrades
    the turn honestly (the report will show it, the judge will fail it);
  - MCP_B2C reachable (staging) for real hotel data.
Profile continuity is provided in-process by an injected fakeredis store — no
Redis server required.

Usage:
  python scripts/run_dynamic_conversation_regression.py
  python scripts/run_dynamic_conversation_regression.py --families simple_search,compare
  python scripts/run_dynamic_conversation_regression.py --limit 1   # one per family (smoke)
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _load_dotenv() -> None:
    """Minimal .env loader (KEY=VALUE lines) — only sets keys absent from the
    environment, so `source .env` / real env always win. No new dependency."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--families",
        default="",
        help="Comma-separated family filter (default: all 8).",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Max scenarios per family (default: all)."
    )
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "evals" / "reports" / "conversation_battery.json"),
        help="Where to write the JSON report.",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress per-scenario progress.")
    args = parser.parse_args()

    _load_dotenv()
    # The battery drives the concierge in-process, so it plays the concierge's
    # role toward the leaves and must send the SAME outbound D7 bearer that
    # run_local.sh gives them (fail-closed leaves 401 an unauthenticated leg,
    # which would silently degrade every search/faq turn). Mirror run_local.sh's
    # defaults; a real token in .env/env still wins (setdefault).
    os.environ.setdefault("A2A_BEARER_TOKEN", "local-dev-token")
    os.environ.setdefault("HOTEL_SEARCH_A2A_TOKEN", os.environ["A2A_BEARER_TOKEN"])
    os.environ.setdefault("FAQ_AGENT_A2A_TOKEN", os.environ["A2A_BEARER_TOKEN"])
    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "run_dynamic_conversation_regression: OPENAI_API_KEY not set — the live "
            "battery needs it for triage/synthesis/judge. Aborting.",
            file=sys.stderr,
        )
        return 2

    from evals.battery import load_scenarios, run_battery_sync

    families = [f.strip() for f in args.families.split(",") if f.strip()] or None
    scenarios = load_scenarios(families=families, limit=args.limit)
    if not scenarios:
        print("run_dynamic_conversation_regression: no scenarios matched the filter.", file=sys.stderr)
        return 2

    print(
        f"battery → {len(scenarios)} scenario(s), judge={os.environ.get('RELEASE_GATE_JUDGE_MODEL', os.environ.get('DAYUSE_MODEL', 'gpt-4o-mini'))}",
        flush=True,
    )
    report = run_battery_sync(scenarios, progress=not args.quiet)
    report["generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    report["judge_model"] = os.environ.get(
        "RELEASE_GATE_JUDGE_MODEL", os.environ.get("DAYUSE_MODEL", "gpt-4o-mini")
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = report["summary"]
    print(f"\n{'='*56}")
    print(f"battery: {summary['passed']}/{summary['total']} scenarios passed")
    print("per-family:")
    for fam, stat in summary["by_family"].items():
        print(f"  {fam:<18} {stat['passed']}/{stat['count']}  ({stat['pass_rate']:.0%})")
    print(
        f"budget: max {summary['max_llm_calls_per_turn_observed']} LLM/turn, "
        f"{summary['over_budget_turns']} turn(s) over the cap of 3"
    )
    print(f"report → {out_path}")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
