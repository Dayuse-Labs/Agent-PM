"""OBS6 — import REAL production-trace items into the hosted `b2c/prod-regressions`
dataset, each carrying `source_trace_id` (DoD: >= 5 items imported from real
traces). This is the "failed-in-prod -> regression case" loop (OBS6 phase §3).

Source of truth for WHICH traces: `evals/datasets/b2c-prod-regressions.jsonl`
— a curated list (`id`, `source_trace_id`, `expected_output`, `metadata`),
each `source_trace_id` naming a real Langfuse trace already documented in
HANDOFF.md (the concierge's `v3.chat` trace for that turn, per D-OBS-5 "1
trace = 1 tour"). Deciding WHAT the correct expected behaviour is needs a
human reading the incident — this script only handles the mechanical, replay-
safe part: verify each referenced trace still exists (never import a dead
reference silently), pull `input.messages` from the trace's OWN recorded
input (single source of truth — never a hand-transcription that could drift
from what actually happened), and upsert into the hosted dataset.
Upsert can overwrite hosted corrections for those ids. Export and reconcile
hosted annotations before maintenance imports; CI must not run this script.

A prod trace is a single completed turn, not a fixture: it never carries a
`profile` (turn_index 0 in every curated case so far) — a future item
importing a LATER turn of a session would need one, same N+1 discipline as
the hand-authored families (see evals/datasets/README.md); not needed here.

Usage:
    .venv/bin/python scripts/langfuse_import_dataset.py             # verify + upsert
    .venv/bin/python scripts/langfuse_import_dataset.py --dry-run   # verify only, no upsert
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

CURATED_PATH = Path(__file__).resolve().parent.parent / "evals" / "datasets" / "b2c-prod-regressions.jsonl"
DATASET_NAME = "b2c/prod-regressions"

_REQUIRED_KEYS = ("id", "source_trace_id", "expected_output", "metadata")


def load_curated(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        item = json.loads(raw)
        missing = [key for key in _REQUIRED_KEYS if key not in item]
        if missing:
            raise SystemExit(f"{path.name}:{lineno}: missing keys {missing}")
        if item["id"] in seen_ids:
            raise SystemExit(f"{path.name}:{lineno}: duplicate id {item['id']!r}")
        seen_ids.add(item["id"])
        items.append(item)
    if not items:
        raise SystemExit(f"{path.name}: no items")
    return items


def _fetch_trace_input(langfuse: Any, trace_id: str) -> str:
    """The trace's own recorded input text, or raises if the trace is gone —
    a dead source_trace_id must fail loudly, never silently drop the item
    (that would be an audit gap, not a graceful degradation)."""
    trace = langfuse.api.trace.get(trace_id, fields="core,io")
    if not isinstance(trace.input, str) or not trace.input.strip():
        raise SystemExit(f"trace {trace_id}: no text input recorded — can't build a replayable item")
    return trace.input


def build_items(langfuse: Any, curated: list[dict[str, Any]]) -> list[dict[str, Any]]:
    built = []
    for entry in curated:
        message = _fetch_trace_input(langfuse, entry["source_trace_id"])
        built.append(
            {
                "id": entry["id"],
                "source_trace_id": entry["source_trace_id"],
                "input": {"messages": [{"role": "user", "content": message}], "profile": {}},
                "expected_output": entry["expected_output"],
                "metadata": entry["metadata"],
            }
        )
        print(f"  {entry['id']}: verified trace {entry['source_trace_id']} — {message[:70]!r}")
    return built


def run(dry_run: bool) -> None:
    curated = load_curated(CURATED_PATH)
    print(f"loaded {len(curated)} curated regression case(s) from {CURATED_PATH.name}")

    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        if not os.environ.get(key):
            raise SystemExit(f"{key} is not set — source your .env first (never hardcode keys)")

    from langfuse import Langfuse  # late import: keep --dry-run's failure mode obvious

    langfuse = Langfuse()
    items = build_items(langfuse, curated)
    if dry_run:
        print(f"dry-run: {len(items)} item(s) verified, nothing upserted")
        return

    langfuse.create_dataset(
        name=DATASET_NAME,
        description="Real production turns tied to documented HANDOFF.md incidents — each item's "
        "source_trace_id is the actual trace that motivated it.",
        metadata={"source": "scripts/langfuse_import_dataset.py"},
    )
    for item in items:
        langfuse.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=item["id"],
            source_trace_id=item["source_trace_id"],
            input=item["input"],
            expected_output=item["expected_output"],
            metadata=item["metadata"],
        )
    langfuse.flush()  # short-lived process — without this, queued events are lost
    print(f"upserted {len(items)} item(s) into {DATASET_NAME!r} (flushed)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="verify traces exist, no upsert")
    args = parser.parse_args()
    try:
        run(args.dry_run)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — one honest line, never a token in a stack trace
        print(f"import failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
