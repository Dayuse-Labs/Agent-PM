"""Replay an immutable production export, sequentially within each conversation.

No historical assistant answer is used as a correctness label. Raw inputs and
outputs must stay under ignored baseline/. This runner only targets loopback
services launched by replay_runtime and never invokes a booking/cancellation API.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import time
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from evals.production_corpus import atomic_json

VERSION = 1
SYNTHETIC = re.compile(r"^(?:eval|qa|smoke|test|codex|claude|prodlike|intl)[_-]", re.I)
FAQ = re.compile(r"annul|cancel|refund|rembours|paiement|payment|carte bancaire|credit card|faq|réservation|reservation", re.I)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def context_for(row: dict) -> tuple[dict, list[str]]:
    """Only recorded request-derived fields, never an old model's active_filters.

    Logs do not contain the full browser context (GPS, timezone, booking history).
    Market inference is not a substitute for those missing request fields.
    """
    market = row.get("detected_market") or {}
    diag = market.get("_diag") or {}
    context = {}
    for target, key in (("locale", "url_locale"), ("currency", "url_currency")):
        if diag.get(key):
            context[target] = diag[key]
    domain = row.get("client_domain") or diag.get("x_dayuse_domain")
    if not domain:
        for key in ("origin", "referer"):
            if diag.get(key):
                host = urlparse(diag[key]).hostname
                if host and re.fullmatch(r"(?:www\.)?dayuse\.[a-z.]+", host):
                    domain = host
                    break
    if domain:
        context["domain"] = domain
    return context, [k for k in ("locale", "currency", "domain", "client_timezone", "geolocation", "user_context") if k not in context]


def compile_cases(rows: list[dict]) -> tuple[list[dict], dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    excluded = []
    for row in rows:
        if not str(row.get("user_message") or "").strip():
            excluded.append({"row_id": row["id"], "reason": "empty_user_message"})
            continue
        if not row.get("session_id"):
            raise ValueError("nonempty turn has no session identity")
        groups[str(row["session_id"])].append(row)
    cases = []
    missing: Counter = Counter()
    for sid, turns in groups.items():
        turns.sort(key=lambda r: (r["created_at"], int(r["id"])))
        prepared = []
        for row in turns:
            clock = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
            # Legacy Postgres export uses naive UTC; explicit assumption in manifest.
            if clock.tzinfo is None:
                clock = clock.replace(tzinfo=UTC)
            context, absent = context_for(row)
            missing.update(absent)
            prepared.append({"row_id": row["id"], "clock": clock.isoformat(),
                             "body": {"message": row["user_message"], **context},
                             "missing_context": absent})
        # Identical conversations share a split, so duplicates cannot leak into holdout.
        group_hash = digest([re.sub(r"\s+", " ", t["body"]["message"].strip().casefold()) for t in prepared])
        bucket = int(group_hash[:8], 16) % 10
        cases.append({"id": digest(sid)[:24], "group_hash": group_hash,
                      "split": "dev" if bucket < 6 else "validation" if bucket < 8 else "holdout",
                      "traffic": "explicit_synthetic" if SYNTHETIC.match(sid) else "unclassified",
                      "family_hint": "faq_or_booking" if any(FAQ.search(t["body"]["message"]) for t in prepared) else "other",
                      "turns": prepared})
    cases.sort(key=lambda c: c["id"])
    return cases, {"source_rows": len(rows), "eligible_turns": sum(len(c["turns"]) for c in cases),
                   "sessions": len(cases), "excluded": excluded, "missing_context_turns": dict(missing),
                   "traffic": dict(Counter(c["traffic"] for c in cases)),
                   "splits": dict(Counter(c["split"] for c in cases)),
                   "family_hints": dict(Counter(c["family_hint"] for c in cases))}


async def request_turn(client: httpx.AsyncClient, endpoint: str, body: dict, headers: dict) -> dict:
    start = time.monotonic()
    first: dict[str, float] = {}
    event = "message"
    data: list[str] = []
    done = None
    trace_id = None
    async with client.stream("POST", endpoint, json=body, headers=headers) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
            elif not line and data:
                first.setdefault(event, round((time.monotonic() - start) * 1000, 2))
                payload = json.loads("\n".join(data))
                if event == "done":
                    done = payload
                if event == "progress" and isinstance(payload, dict):
                    trace_id = payload.get("trace_id") or trace_id
                data = []
                event = "message"
    if not isinstance(done, dict) or "message" not in done:
        raise ValueError("stream ended without a final chat payload")
    return {"response": done, "trace_id": trace_id,
            "timing_ms": {**first, "total": round((time.monotonic() - start) * 1000, 2)}}


async def run_case(case: dict, directory: Path, endpoint: str, variant: str, run_id: str,
                   timeout: float, fixture_health: str | None = None) -> dict:
    path = directory / "cases" / (case["id"] + ".json")
    previous_sessions = []
    if path.exists():
        saved = json.loads(path.read_text())
        if saved.get("input_hash") != digest(case):
            raise ValueError("case changed on resume")
        if saved.get("complete"):
            return saved
        previous_sessions = [*saved.get("previous_sessions", []), saved["session_id"]]
    # Partial sessions restart from turn one with a NEW session; never duplicate
    # an uncertain timed-out turn into existing conversational state.
    session = f"eval-preservation-{run_id}-{case['id']}-{uuid.uuid4().hex[:8]}"
    result = {"case_id": case["id"], "input_hash": digest(case), "split": case["split"],
              "traffic": case["traffic"], "family_hint": case["family_hint"],
              "session_id": session, "previous_sessions": previous_sessions, "complete": False, "turns": []}
    async with httpx.AsyncClient(timeout=timeout) as client:
        for index, turn in enumerate(case["turns"], 1):
            headers = {"X-Dayuse-Synthetic": "1", "X-Client-Session-Id": session,
                       "X-Replay-Clock": turn["clock"], "X-Replay-Source-Today": turn["clock"][:10],
                       "X-Replay-Case": case["id"], "X-Replay-Turn": str(index), "X-Replay-Variant": variant,
                       "X-Replay-Session-Id": session}
            try:
                health_before = None
                if fixture_health:
                    health_response = await client.get(fixture_health)
                    health_response.raise_for_status()
                    health_before = health_response.json()
                    if not health_before["ready"]:
                        raise ValueError("fixture provider is rate limited")
                out = await request_turn(client, endpoint, {**turn["body"], "session_id": session}, headers)
                if fixture_health:
                    health_response = await client.get(fixture_health)
                    health_response.raise_for_status()
                    health_after = health_response.json()
                    if health_after["error_count"] != health_before["error_count"]:
                        raise ValueError("fixture acquisition failed during this turn")
                result["turns"].append({"row_id": turn["row_id"], "index": index, **out})
            except (httpx.HTTPError, ValueError) as exc:
                result["error"] = {"turn": index, "type": type(exc).__name__}
                atomic_json(path, result)
                return result
            atomic_json(path, result)
    result["complete"] = True
    atomic_json(path, result)
    return result


async def replay(cases: list[dict], directory: Path, endpoint: str, variant: str,
                 concurrency: int, provenance: dict, timeout: float = 100,
                 fixture_health: str | None = None) -> dict:
    if urlparse(endpoint).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("production replay may only target a local evaluation runtime")
    if (directory / "INVALIDATED.json").exists():
        raise ValueError("invalidated run cannot be resumed; use a new output directory")
    manifest_path = directory / "manifest.json"
    identity = {"version": VERSION, "cases_hash": digest(cases), "endpoint": endpoint,
                "variant": variant, "provenance": provenance, "concurrency": concurrency,
                "fixture_health": fixture_health}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest["identity"] != identity:
            raise ValueError("run configuration changed; use a new output directory")
    else:
        manifest = {"identity": identity, "run_id": uuid.uuid4().hex[:10],
                    "started_at": datetime.now(UTC).isoformat(), "complete": False,
                    "expected_sessions": len(cases), "expected_turns": sum(len(c["turns"]) for c in cases)}
        atomic_json(manifest_path, manifest)
    queue: asyncio.Queue = asyncio.Queue()
    for case in cases:
        queue.put_nowait(case)
    counts: Counter = Counter()
    stop = asyncio.Event()

    async def worker():
        while not queue.empty() and not stop.is_set():
            case = queue.get_nowait()
            result = await run_case(case, directory, endpoint, variant, manifest["run_id"], timeout, fixture_health)
            if not result["complete"]:
                stop.set()  # investigate infrastructure before spending more calls
            counts["complete" if result["complete"] else "incomplete"] += 1
            counts["turns"] += len(result["turns"])
            queue.task_done()
            print(json.dumps({"expected_sessions": len(cases), **counts}), flush=True)
            atomic_json(directory / "progress.json", {"expected_sessions": len(cases), **counts})

    await asyncio.gather(*(worker() for _ in range(concurrency)))
    manifest.update({"complete": counts["complete"] == len(cases), "counts": dict(counts),
                     "finished_at": datetime.now(UTC).isoformat()})
    atomic_json(manifest_path, manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--code-sha", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--inventory-day", required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--split", choices=["dev", "validation", "holdout"])
    parser.add_argument("--fixture-health", default="http://127.0.0.1:8370/status")
    args = parser.parse_args()
    if args.concurrency < 1 or (args.limit is not None and args.limit < 1):
        parser.error("concurrency and limit must be positive")
    raw = args.corpus.read_bytes()
    cases, inventory = compile_cases([json.loads(line) for line in raw.splitlines()])
    if args.split:
        cases = [c for c in cases if c["split"] == args.split]
    if args.limit:
        # Pilot starts with FAQ/booking cases to exercise the additional leaf.
        cases = sorted(cases, key=lambda c: (c["family_hint"] != "faq_or_booking", c["id"]))[:args.limit]
    atomic_json(args.output / "inventory.json", inventory)
    provenance = {"corpus_sha256": hashlib.sha256(raw).hexdigest(), "code_sha": args.code_sha,
                  "model": args.model, "inventory_day": args.inventory_day, "split": args.split,
                  "limit": args.limit, "naive_log_timezone": "UTC", "unrecorded_timezone": "not_reconstructed",
                  "inventory": "shared contemporary MCP fixtures, not historical availability"}
    result = asyncio.run(replay(cases, args.output, args.endpoint, args.variant, args.concurrency, provenance,
                               fixture_health=args.fixture_health))
    raise SystemExit(0 if result["complete"] else 1)


if __name__ == "__main__":
    main()
