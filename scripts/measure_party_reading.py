#!/usr/bin/env python3
"""2026-11-02 (prod audit): does the triage still read a date, an hour, a
duration or a distance as a party size?

Since #173 every « how many adults and children? » asked in prod was false
(10 of 10): « 11.11. », « From 4pm », « 3 horas », « 30km »… became 11, 4, 3
and 30 people. This runs the REAL `triage.classify()` (its model and prompt) on
`evals/party_reading_inputs.jsonl`: the prod shapes (reworded, same numbers,
units and previous turns) must carry no party, the real party statements their
total. Each row also keeps the model's raw `requested_occupancy`, to tell what
the model said from what the code kept.

`--compare A B` calls nothing: it reads two `run` outputs of
`evals/triage_inputs.jsonl` and prints the inputs whose family or language
changed (prompt drift between two code versions).

Costs triage calls only. Run with the local .env (no DAYUSE_MODEL*, so the
code default: luna, the prod triage model) and Langfuse off:
    set -a && . ./.env && set +a
    env -u LANGFUSE_PUBLIC_KEY -u LANGFUSE_SECRET_KEY DISABLE_AIOHTTP_TRANSPORT=True \\
      PYTHONPATH=agents/b2c_concierge .venv/bin/python scripts/measure_party_reading.py \\
      run --runs 3 --out party.jsonl
Never reads user data.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Any

FIXTURE = Path(__file__).resolve().parents[1] / "evals" / "party_reading_inputs.jsonl"

#: The raw text of the last triage completion (the patch below), sequential calls only.
_LAST_RAW: dict[str, Any] = {}


def _capture_raw() -> None:
    import litellm

    original = litellm.acompletion

    async def capture(*args: Any, **kwargs: Any) -> Any:
        response = await original(*args, **kwargs)
        try:
            _LAST_RAW["text"] = response.choices[0].message.content
        except (AttributeError, IndexError):
            _LAST_RAW["text"] = None
        return response

    litellm.acompletion = capture


def _raw_occupancy() -> Any:
    try:
        return json.loads(_LAST_RAW.get("text") or "").get("requested_occupancy")
    except (ValueError, AttributeError):
        return None


def _party_total(occupancy: dict[str, int] | None) -> int | None:
    if not occupancy:
        return None
    if occupancy.get("total") is not None:
        return occupancy["total"]
    return sum(occupancy.get(key) or 0 for key in ("adults", "children")) or None


async def run(inputs: Path, runs: int, out: Path) -> None:
    from b2c_concierge.budget import TurnBudget
    from b2c_concierge.triage import classify

    _capture_raw()
    items = [json.loads(line) for line in inputs.read_text().splitlines() if line.strip()]
    passed: dict[str, list[int]] = {"none": [0, 0], "party": [0, 0]}
    with out.open("w", encoding="utf-8") as sink:
        for item in items:
            for draw in range(runs):
                _LAST_RAW.clear()
                triage = await classify(item["message"], TurnBudget(), "party-reading",
                                        recent_messages=item.get("recent_messages"),
                                        previous_question=item.get("previous_question"))
                row = {
                    "id": item.get("id") or item.get("key"), "draw": draw,
                    "family": triage.family, "language": triage.language,
                    "occupancy": triage.requested_occupancy, "out_of_range": triage.occupancy_out_of_range,
                    "raw_occupancy": _raw_occupancy(),
                }
                if "expect" in item:
                    expect = item["expect"]
                    ok = (triage.requested_occupancy is None and triage.occupancy_out_of_range is None
                          if expect is None else _party_total(triage.requested_occupancy) == expect)
                    kind = "none" if expect is None else "party"
                    passed[kind][0] += int(ok)
                    passed[kind][1] += 1
                    row.update(expect=expect, ok=ok)
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(json.dumps(row, ensure_ascii=False), flush=True)
    for kind, (ok, total) in passed.items():
        if total:
            print(f"{kind}: {ok}/{total}")


def compare(before: Path, after: Path) -> None:
    def majority(path: Path) -> dict[str, tuple[str, str]]:
        votes: dict[str, Counter] = {}
        for line in path.read_text().splitlines():
            row = json.loads(line)
            votes.setdefault(row["id"], Counter())[(row["family"], row["language"])] += 1
        return {key: counter.most_common(1)[0][0] for key, counter in votes.items()}

    a, b = majority(before), majority(after)
    changed = [key for key in a if key in b and a[key] != b[key]]
    print(f"inputs compared: {len(set(a) & set(b))}, family/language changed: {len(changed)}")
    for key in changed:
        print(f"  {key}: {a[key]} -> {b[key]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--inputs", type=Path, default=FIXTURE)
    p_run.add_argument("--runs", type=int, default=3)
    p_run.add_argument("--out", type=Path, required=True)
    p_cmp = sub.add_parser("compare")
    p_cmp.add_argument("before", type=Path)
    p_cmp.add_argument("after", type=Path)
    args = parser.parse_args()
    if args.mode == "run":
        asyncio.run(run(args.inputs, args.runs, args.out))
    else:
        compare(args.before, args.after)
