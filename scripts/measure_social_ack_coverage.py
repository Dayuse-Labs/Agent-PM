#!/usr/bin/env python3
"""UX6 follow-up — what does a bare non-fr/en "thanks" actually cost?

The open item UX2 left behind and never measured (preserved in HANDOFF
2026-08-28 before its phase file was deleted): `_ACK_WORDS` / `_ACK_RE`
(`triage.py:101-107`) are fr/en only, so `is_social_ack` does not match a bare
"grazie" / "danke" / "gracias" / "obrigado" / "bedankt". Those messages skip the
zero-LLM ack template and go to the LLM triage instead.

The phase's instruction was explicit: **measure, then decide — do not inflate
the regex by reflex.** So this script answers the two questions that decide it,
and deliberately changes nothing:

  1. CORRECTNESS — does the LLM triage classify a bare non-fr/en social word as
     `family="ack"` anyway? If yes, the user sees the same answer and this is
     purely a cost question. If no, it is a defect, not an optimisation.
  2. COST — what does that one extra economy call actually cost, in tokens,
     dollars and latency?

`agent.py:1002-1010` already states the DESIGN intent ("A Spanish 'sí' or a
German 'ja' never matches it and never reaches this line at all; it goes to
triage like any other substantive message"). This measures whether that intent
holds up in practice.

Each phrase is classified N times (default 3) because gpt-4o-mini is not
deterministic on short cross-lingual input — the NL finding of UX2 (a short
"hotel in Amsterdam morgen" classified as `en`) is the same failure mode, so a
single run per phrase would be worthless.

Real LLM calls: needs OPENAI_API_KEY. NOT a pytest (CLAUDE.md: pytest stays
offline). Same posture as scripts/probe_currency_priceeuro.py.

Usage:
    set -a; . ./.env; set +a
    .venv/bin/python scripts/measure_social_ack_coverage.py
    .venv/bin/python scripts/measure_social_ack_coverage.py --reps 5 --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time

_CONCIERGE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "agents", "b2c_concierge",
)
if _CONCIERGE not in sys.path:
    sys.path.insert(0, _CONCIERGE)

from b2c_concierge import triage  # noqa: E402
from b2c_concierge.budget import TurnBudget  # noqa: E402

#: (language, phrase, kind). `kind` is bookkeeping: "greeting" or "thanks".
#: fr/en rows are the CONTROL — they must short-circuit and cost nothing.
PHRASES: tuple[tuple[str, str, str], ...] = (
    # -- control: already matched by _ACK_WORDS, must never reach the LLM ------
    ("fr", "bonjour", "greeting"),
    ("fr", "merci", "thanks"),
    ("en", "hello", "greeting"),
    ("en", "thanks", "thanks"),
    # -- the gap: recognized languages (UX2) with no ack words ----------------
    ("es", "hola", "greeting"),
    ("es", "gracias", "thanks"),
    ("it", "ciao", "greeting"),
    ("it", "grazie", "thanks"),
    ("de", "hallo", "greeting"),
    ("de", "danke", "thanks"),
    ("pt", "olá", "greeting"),
    ("pt", "obrigado", "thanks"),
    ("nl", "hallo", "greeting"),
    ("nl", "bedankt", "thanks"),
    # -- two-word variants: closer to what people actually type ---------------
    ("es", "muchas gracias", "thanks"),
    ("it", "grazie mille", "thanks"),
    ("de", "vielen dank", "thanks"),
    ("pt", "muito obrigado", "thanks"),
    ("nl", "hartelijk bedankt", "thanks"),
)


async def _classify_once(phrase: str) -> dict[str, object]:
    budget = TurnBudget()
    t0 = time.monotonic()
    try:
        result = await triage.classify(phrase, budget, invocation_id="ux6-ack-measure")
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        return {
            "family": result.family,
            "language": result.language,
            "llm_calls": budget.llm_calls,
            "ms": round(elapsed_ms, 1),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 — a probe reports, never raises
        return {
            "family": None, "language": None, "llm_calls": budget.llm_calls,
            "ms": round((time.monotonic() - t0) * 1000.0, 1), "error": f"{type(exc).__name__}: {exc}",
        }


async def _run(reps: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for language, phrase, kind in PHRASES:
        short_circuits = triage.is_social_ack(phrase)
        row: dict[str, object] = {
            "language": language,
            "phrase": phrase,
            "kind": kind,
            "is_social_ack": short_circuits,
            "runs": [],
        }
        if short_circuits:
            # ZERO LLM by construction — calling classify would measure nothing
            # about this path and would spend a call the real turn never spends.
            row["note"] = "short-circuited by _ACK_RE: 0 LLM calls, template reply"
        else:
            for _ in range(reps):
                row["runs"].append(await _classify_once(phrase))
                await asyncio.sleep(0.4)
        rows.append(row)
    return rows


def _summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    reached_llm = [r for r in rows if not r["is_social_ack"]]
    all_runs = [run for r in reached_llm for run in r["runs"]]  # type: ignore[index]
    ack_runs = [run for run in all_runs if run["family"] == "ack"]
    latencies = [float(run["ms"]) for run in all_runs if run["error"] is None]
    by_phrase_ack_rate = {
        f"{r['language']}:{r['phrase']}": (
            sum(1 for run in r["runs"] if run["family"] == "ack") / len(r["runs"])  # type: ignore[index,arg-type]
            if r["runs"] else None  # type: ignore[index]
        )
        for r in reached_llm
    }
    non_ack = {
        f"{r['language']}:{r['phrase']}": sorted(
            {str(run["family"]) for run in r["runs"] if run["family"] != "ack"}  # type: ignore[index]
        )
        for r in reached_llm
        if any(run["family"] != "ack" for run in r["runs"])  # type: ignore[index]
    }
    return {
        "phrases_short_circuited": sum(1 for r in rows if r["is_social_ack"]),
        "phrases_reaching_the_llm": len(reached_llm),
        "llm_runs": len(all_runs),
        "classified_ack": len(ack_runs),
        "ack_rate": round(len(ack_runs) / len(all_runs), 4) if all_runs else None,
        "median_ms": round(statistics.median(latencies), 1) if latencies else None,
        "p_max_ms": round(max(latencies), 1) if latencies else None,
        "ack_rate_by_phrase": by_phrase_ack_rate,
        "families_other_than_ack": non_ack,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY missing — run: set -a; . ./.env; set +a")
        raise SystemExit(1)

    rows = asyncio.run(_run(args.reps))
    summary = _summarize(rows)

    if args.json:
        print(json.dumps({"model_role": "TRIAGE", "reps": args.reps,
                          "rows": rows, "summary": summary}, indent=2, ensure_ascii=False))
        return

    print(f"reps per phrase: {args.reps}   triage model role: TRIAGE")
    print()
    header = f"{'lang':<6}{'phrase':<20}{'ack_re':<8}{'families seen':<28}{'median ms':>10}"
    print(header)
    print("-" * len(header))
    for row in rows:
        if row["is_social_ack"]:
            print(f"{row['language']:<6}{row['phrase']:<20}{'YES':<8}"
                  f"{'(0 LLM calls — template)':<28}{0:>10}")
            continue
        runs = row["runs"]  # type: ignore[index]
        families = sorted({str(r["family"]) for r in runs})
        lat = [float(r["ms"]) for r in runs if r["error"] is None]
        med = round(statistics.median(lat), 1) if lat else float("nan")
        print(f"{row['language']:<6}{row['phrase']:<20}{'no':<8}"
              f"{','.join(families):<28}{med:>10}")
    print()
    print("SUMMARY")
    for key, value in summary.items():
        if key in {"ack_rate_by_phrase", "families_other_than_ack"}:
            continue
        print(f"  {key}: {value}")
    if summary["families_other_than_ack"]:
        print("  ⚠ MISCLASSIFIED (family != ack):")
        for phrase, families in summary["families_other_than_ack"].items():  # type: ignore[union-attr]
            print(f"      {phrase} -> {families}")
    else:
        print("  no misclassification: every phrase that reached the LLM came back 'ack'")


if __name__ == "__main__":
    main()
