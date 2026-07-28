#!/usr/bin/env python
"""Latency baseline — per-phase timings of a scripted conversation, e2e.

Drives N runs of the SAME 5-turn conversation through the public facade's SSE
endpoint (`/v3/chat/stream`) and records, per turn, the wall-clock delta from
the request to each frame the contract emits:

  t_progress   — first `progress` frame (the real TTFT of the SSE path)
  t_hotels     — `hotels` frame (cards are renderable from here)
  t_first_tok  — first `token` frame (synthesis text starts flushing)
  t_card       — `booking_card` frame (booking turns only)
  t_done       — terminal `done` frame. The deployed widget uses the blocking
                 POST `/v3/chat`, which does the same work minus SSE framing:
                 t_done ≈ what a widget user waits today.

Turns: ack, search, refine (amenity+budget), pick ("le moins cher" — booking
family, inline MCP path), faq. One `X-Client-Session-Id` per run (session
continuity), a FRESH one per run (no cross-run contamination). Prompt-token
growth across turns is NOT visible here — join with the server's stdout
metrics (`dayuse_metric=llm_call … prompt_tokens=`, `concierge_metric=turn`)
via the session ids this script prints.

All requests carry `X-Dayuse-Synthetic: 1` (GDPR: filterable synthetic
traffic). No message content is logged beyond this script's own prompts.

Usage:
  python scripts/measure_latency_e2e.py                    # local, 5 runs
  CONCIERGE_URL=https://… python scripts/measure_latency_e2e.py --runs 3
  python scripts/measure_latency_e2e.py --out reports/latency/baseline.jsonl
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import statistics
import sys
import time
import uuid
from typing import Any

import httpx

CONCIERGE_URL = os.environ.get("CONCIERGE_URL", "http://localhost:8100").rstrip("/")
TIMEOUT_SECONDS = float(os.environ.get("MEASURE_TIMEOUT_SECONDS", "90"))

_TOMORROW = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

TURNS: list[tuple[str, str]] = [
    ("ack", "Bonjour !"),
    ("search", f"Je cherche un hôtel en journée à Paris le {_TOMORROW}"),
    ("refine", "Avec piscine, budget max 150€"),
    ("pick", "Je prends le moins cher"),
    ("faq", "Quelles sont les conditions d'annulation d'une réservation Dayuse ?"),
]

# The frame kinds we timestamp (first occurrence only, per turn).
_PHASES = ("progress", "hotels", "token", "booking_card", "done")


def _headers(session_id: str) -> dict[str, str]:
    headers = {"X-Client-Session-Id": session_id, "X-Dayuse-Synthetic": "1"}
    api_key = os.environ.get("CHAT_API_KEY", "").strip()
    if api_key:
        headers["X-Internal-Api-Key"] = api_key
    return headers


def measure_turn(client: httpx.Client, label: str, message: str, session_id: str) -> dict[str, Any]:
    """One turn over SSE; returns {label, ok, ms per first-seen frame, n_tokens}."""
    record: dict[str, Any] = {"turn": label, "ok": False, "n_tokens": 0}
    t0 = time.monotonic()
    event_name = ""
    try:
        with client.stream(
            "POST",
            f"{CONCIERGE_URL}/v3/chat/stream",
            json={"message": message},
            headers=_headers(session_id),
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    event_name = line.split(":", 1)[1].strip()
                    continue
                if not line.startswith("data:") or event_name not in _PHASES:
                    continue
                ms = int((time.monotonic() - t0) * 1000)
                if event_name == "token":
                    record["n_tokens"] += 1
                key = f"t_{event_name}"
                record.setdefault(key, ms)
                if event_name == "done":
                    record["ok"] = True
                    break
    except Exception as exc:  # noqa: BLE001 — a probe failure is a data point, not a crash
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def run_conversation(client: httpx.Client, run_index: int) -> list[dict[str, Any]]:
    session_id = uuid.uuid4().hex
    print(f"run {run_index}: session_id={session_id}")
    records = []
    for label, message in TURNS:
        record = measure_turn(client, label, message, session_id)
        record["run"] = run_index
        record["session_id"] = session_id
        status = "OK  " if record["ok"] else "FAIL"
        phases = "  ".join(
            f"{phase.removeprefix('t_')}={record[phase]}ms"
            for phase in ("t_progress", "t_hotels", "t_token", "t_booking_card", "t_done")
            if phase in record
        )
        print(f"  {status} {label:<8} {phases}{'  ' + record.get('error', '') if not record['ok'] else ''}")
        records.append(record)
    return records


def _percentile_row(values: list[int]) -> str:
    if not values:
        return "—"
    p50 = int(statistics.median(values))
    return f"{p50} / {max(values)}"


def summarize(records: list[dict[str, Any]]) -> None:
    print("\nper-turn p50/max ms across runs (only turns that completed):")
    print(f"{'turn':<8} {'progress':>12} {'hotels':>12} {'first_tok':>12} {'done':>12}")
    for label, _ in TURNS:
        rows = [r for r in records if r["turn"] == label and r["ok"]]
        cols = [
            _percentile_row([r[k] for r in rows if k in r])
            for k in ("t_progress", "t_hotels", "t_token", "t_done")
        ]
        print(f"{label:<8} {cols[0]:>12} {cols[1]:>12} {cols[2]:>12} {cols[3]:>12}")
    failed = [r for r in records if not r["ok"]]
    if failed:
        print(f"\n{len(failed)} turn(s) FAILED — timings above cover completed turns only.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5, help="number of conversation runs (default 5)")
    parser.add_argument("--out", help="append raw per-turn records to this JSONL file")
    args = parser.parse_args()

    print(f"measure_latency_e2e → {CONCIERGE_URL}  ({args.runs} runs × {len(TURNS)} turns)")
    all_records: list[dict[str, Any]] = []
    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        for i in range(1, args.runs + 1):
            all_records += run_conversation(client, i)

    summarize(all_records)

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "a", encoding="utf-8") as fh:
            stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
            for record in all_records:
                fh.write(json.dumps({"ts": stamp, "url": CONCIERGE_URL, **record}) + "\n")
        print(f"raw records appended to {args.out}")

    return 0 if all(r["ok"] for r in all_records) else 1


if __name__ == "__main__":
    sys.exit(main())
