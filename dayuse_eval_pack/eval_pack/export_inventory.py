"""Create a deterministic, privacy-minimized inventory snapshot for offline evals."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PACK = Path(__file__).resolve().parent
ROOT = PACK.parent


def _compact_rate_plan(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("rate_plan_id") or row.get("id"),
        "start_time": row.get("start_time"),
        "end_time": row.get("end_time"),
        "duration_hours": row.get("duration_hours"),
        "price": row.get("price"),
        "original_price": row.get("original_price"),
        "booking_fee": row.get("booking_fee"),
        "currency": row.get("currency"),
        "is_available": bool(row.get("is_available", True)),
        "available_days": list(row.get("available_days") or []),
        "rate_plan_name": row.get("rate_plan_name") or row.get("name"),
        "room_type": row.get("room_type"),
        "bed_type": row.get("bed_type"),
        "addons_included": list(row.get("addons_included") or []),
    }


def compact_hotel(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "hotel_id": row.get("hotel_id") or row.get("id"),
        "name": row.get("name"),
        "country_code": row.get("country_code"),
        "city": row.get("city"),
        "metro": row.get("metro"),
        "zone": row.get("primary_zone") or row.get("zone"),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "stars": row.get("stars"),
        "rating": row.get("rating"),
        "currency": row.get("currency"),
        "min_price": row.get("min_price"),
        "max_price": row.get("max_price"),
        "amenities": list(row.get("amenities") or []),
        "has_pool": bool(row.get("has_pool")),
        "has_spa": bool(row.get("has_spa")),
        "has_air_conditioning": bool(row.get("has_air_conditioning")),
        "is_airport_hotel": bool(row.get("is_airport_hotel")),
        "room_features": row.get("room_features") or {},
        "rate_plans": [
            _compact_rate_plan(plan)
            for plan in row.get("rate_plans") or []
            if isinstance(plan, dict)
        ],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def export_snapshot(source_dir: Path, output: Path, manifest_path: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    source_files: list[dict[str, Any]] = []
    market_counts: Counter[str] = Counter()
    for path in sorted(source_dir.glob("structured_hotels_*.json")):
        if "_enriched" in path.name or path.name.endswith(".bak"):
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            continue
        source_files.append(
            {
                "name": path.name,
                "rows": len(payload),
                "sha256": _sha256(path),
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
            }
        )
        for item in payload:
            if not isinstance(item, dict):
                continue
            compact = compact_hotel(item)
            rows.append(compact)
            market_counts[str(compact.get("country_code") or "unknown").upper()] += 1

    rows.sort(key=lambda row: (str(row.get("country_code") or ""), str(row.get("hotel_id") or "")))
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        output.open("wb") as raw_handle,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as zipped,
        io.TextIOWrapper(zipped, encoding="utf-8", newline="\n") as handle,
    ):
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_kind": "tracked_repository_exports",
        "production_fresh": False,
        "warning": (
            "This snapshot comes from tracked repository exports, not a live production query. "
            "Regenerate from an approved fresh export before using it as current production truth."
        ),
        "privacy": {
            "removed": ["address", "photos", "descriptions", "reviews", "orders", "customer data"],
            "contains_customer_pii": False,
        },
        "hotels": len(rows),
        "rate_plans": sum(len(row.get("rate_plans") or []) for row in rows),
        "markets": dict(sorted(market_counts.items())),
        "output": output.name,
        "output_sha256": _sha256(output),
        "source_files": source_files,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", default=str(ROOT / "data"))
    parser.add_argument("--output", default=str(PACK / "fixtures/inventory_snapshot.jsonl.gz"))
    parser.add_argument(
        "--manifest", default=str(PACK / "fixtures/inventory_snapshot_manifest.json")
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = export_snapshot(Path(args.source_dir), Path(args.output), Path(args.manifest))
    print(
        json.dumps(
            {
                "hotels": manifest["hotels"],
                "markets": len(manifest["markets"]),
                "output_sha256": manifest["output_sha256"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
