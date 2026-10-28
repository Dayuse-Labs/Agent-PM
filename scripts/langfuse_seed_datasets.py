"""Seed the hand-written eval datasets into hosted Langfuse datasets.

Companion of `evals/datasets/*.jsonl` (audit 2026-07-30 — POI + occupancy +
language-robustness families). HOSTED datasets on purpose: a local dataset
creates no DatasetRun, hence no comparison view (OBS6 pitfall #1). Items carry
deterministic ids, so re-running is an upsert — never a duplicate.
Upsert can overwrite hosted corrections for those ids. Export and reconcile
hosted annotations before maintenance imports; CI must not run this script.

This script only SEEDS data. Experiments, evaluators and the CI gate belong to
the OBS6 session (`phases/OBS6-datasets-experiments.md`); the item format here
is the one OBS6 §2 locks (`input = {"messages": [...], "profile": {...}}`,
deterministic assertions in `expected_output`).

Env (same keys the services already use, never printed): LANGFUSE_PUBLIC_KEY,
LANGFUSE_SECRET_KEY, LANGFUSE_HOST. SDK: langfuse==4.14.1 (already pinned in
agents/b2c_concierge/requirements.txt — the repo venv has it).

Usage:
    .venv/bin/python scripts/langfuse_seed_datasets.py             # seed everything
    .venv/bin/python scripts/langfuse_seed_datasets.py --dry-run   # validate files only
    .venv/bin/python scripts/langfuse_seed_datasets.py --only b2c-occupancy
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DATASETS_DIR = Path(__file__).resolve().parent.parent / "evals" / "datasets"

# file stem -> hosted dataset name (the "/" creates a folder in the Langfuse UI, OBS6 §1).
DATASET_NAMES = {
    "b2c-geo-poi": "b2c/geo-poi",
    "b2c-occupancy": "b2c/occupancy",
    "b2c-language-robustness": "b2c/language-robustness",
    "b2c-qa-2026-09-30": "b2c/qa-2026-09-30",
    "b2c-dialogue-state": "b2c/dialogue-state",
    "b2c-geo-class-2026-10-06": "b2c/geo-class-2026-10-06",
    "b2c-qa-14707-2026-10-14": "b2c/qa-14707-2026-10-14",
    "b2c-prod-2026-10-27": "b2c/prod-2026-10-27",
    "b2c-prod-2026-10-28": "b2c/prod-2026-10-28",
}

# OBS6 §2 — lock the item shape server-side so hand-added items can't drift.
INPUT_SCHEMA = {
    "type": "object",
    "required": ["messages"],
    "properties": {
        "messages": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["role", "content"],
                "properties": {
                    "role": {"type": "string", "enum": ["user", "assistant"]},
                    "content": {"type": "string"},
                },
            },
        },
        "profile": {"type": "object"},
    },
}

_REQUIRED_ITEM_KEYS = ("id", "input", "expected_output", "metadata")


def load_items(path: Path) -> list[dict]:
    """Parse + validate one JSONL file. Fails loudly on the first bad line:
    a silently skipped item would turn a dataset hole into a fake green."""
    items: list[dict] = []
    seen_ids: set[str] = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except ValueError as exc:
            raise SystemExit(f"{path.name}:{lineno}: invalid JSON — {exc}") from exc
        missing = [key for key in _REQUIRED_ITEM_KEYS if key not in item]
        if missing:
            raise SystemExit(f"{path.name}:{lineno}: missing keys {missing}")
        if not item["input"].get("messages"):
            raise SystemExit(f"{path.name}:{lineno}: input.messages is empty")
        if item["id"] in seen_ids:
            raise SystemExit(f"{path.name}:{lineno}: duplicate id {item['id']!r}")
        seen_ids.add(item["id"])
        items.append(item)
    if not items:
        raise SystemExit(f"{path.name}: no items")
    return items


def seed(only: str | None, dry_run: bool) -> None:
    stems = [only] if only else sorted(DATASET_NAMES)
    files: dict[str, list[dict]] = {}
    for stem in stems:
        if stem not in DATASET_NAMES:
            raise SystemExit(f"unknown dataset {stem!r} — expected one of {sorted(DATASET_NAMES)}")
        files[stem] = load_items(DATASETS_DIR / f"{stem}.jsonl")

    total = sum(len(v) for v in files.values())
    print(f"validated {total} items across {len(files)} file(s)")
    if dry_run:
        return

    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        if not os.environ.get(key):
            raise SystemExit(f"{key} is not set — source your .env first (never hardcode keys)")

    from langfuse import Langfuse  # late import: --dry-run must work without the SDK

    langfuse = Langfuse()
    for stem, items in files.items():
        name = DATASET_NAMES[stem]
        description = f"Seeded from evals/datasets/{stem}.jsonl (audit 2026-07-30)."
        metadata = {
            "source": f"evals/datasets/{stem}.jsonl",
            "seeded_by": "langfuse_seed_datasets.py",
        }
        try:
            langfuse.create_dataset(
                name=name, description=description, metadata=metadata, input_schema=INPUT_SCHEMA
            )
        except TypeError:
            # SDK/server too old for input_schema (OBS0 checklist point 7 — recent
            # features may be absent on server 3.224.x): the schema lock is a
            # nice-to-have, the seeding must not die on it.
            print(f"  {name}: input_schema unsupported here — created without it")
            langfuse.create_dataset(name=name, description=description, metadata=metadata)
        for item in items:
            langfuse.create_dataset_item(
                dataset_name=name,
                id=item["id"],
                input=item["input"],
                expected_output=item["expected_output"],
                metadata=item["metadata"],
            )
        print(f"  {name}: upserted {len(items)} items")
    # OBS6 §7: short-lived process — without flush the queued events are lost.
    langfuse.flush()
    print("done (flushed)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="seed a single file stem, e.g. b2c-occupancy")
    parser.add_argument(
        "--dry-run", action="store_true", help="validate the JSONL files locally, no network"
    )
    args = parser.parse_args()
    try:
        seed(args.only, args.dry_run)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — one honest line, never a token in a stack trace
        print(f"seeding failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
