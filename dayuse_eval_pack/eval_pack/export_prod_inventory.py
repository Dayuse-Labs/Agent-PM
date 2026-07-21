"""Export a read-only, PII-minimized inventory snapshot from PostgreSQL.

The database URL is read from an environment variable and is never printed.
Only hotel and rate-plan catalogue tables are queried; conversation, session,
customer and booking tables are deliberately out of scope.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import io
import json
import os
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

PACK = Path(__file__).resolve().parent

HOTELS_SQL = """
SELECT
    id, name, country_code, metro, city, primary_zone, latitude, longitude,
    stars, rating, amenities, min_price, max_price, currency, room_features,
    has_air_conditioning, updated_at
FROM hotels
WHERE is_active IS TRUE
ORDER BY country_code, id
"""

RATE_PLANS_SQL = """
SELECT
    rp.id, rp.hotel_id, rp.start_time, rp.end_time, rp.duration_hours,
    rp.price, rp.original_price, rp.booking_fee, rp.currency, rp.is_available,
    rp.available_days, rp.rate_plan_name, rp.room_type, rp.addons_included
FROM rate_plans AS rp
JOIN hotels AS h ON h.id = rp.hotel_id
WHERE h.is_active IS TRUE
ORDER BY rp.hotel_id, rp.id
"""


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _contains(amenities: list[str], *needles: str) -> bool:
    blob = " ".join(str(value).casefold() for value in amenities)
    return any(needle in blob for needle in needles)


async def export_prod_snapshot(
    database_url: str,
    output: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    try:
        import asyncpg
    except ImportError as exc:  # pragma: no cover - depends on repo environment
        raise RuntimeError("asyncpg is required; install the repository dependencies") from exc

    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(dsn=dsn, command_timeout=120)
    try:
        async with connection.transaction(readonly=True):
            await connection.execute("SET LOCAL statement_timeout = '120s'")
            hotel_rows = await connection.fetch(HOTELS_SQL)
            rate_rows = await connection.fetch(RATE_PLANS_SQL)
    finally:
        await connection.close()

    rate_plans: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for raw in rate_rows:
        row = dict(raw)
        rate_plans[int(row.pop("hotel_id"))].append(_json_value(row))

    rows: list[dict[str, Any]] = []
    market_counts: Counter[str] = Counter()
    newest_update: datetime | None = None
    for raw in hotel_rows:
        row = dict(raw)
        updated_at = row.pop("updated_at", None)
        if isinstance(updated_at, datetime) and (
            newest_update is None or updated_at > newest_update
        ):
            newest_update = updated_at
        amenities = list(row.get("amenities") or [])
        hotel_id = int(row.pop("id"))
        zone = row.pop("primary_zone", None)
        compact = {
            "hotel_id": hotel_id,
            **_json_value(row),
            "zone": zone,
            "has_pool": _contains(amenities, "pool", "piscine", "piscina"),
            "has_spa": _contains(amenities, "spa", "wellness", "sauna", "hammam"),
            "is_airport_hotel": _contains(amenities, "airport shuttle"),
            "rate_plans": rate_plans.get(hotel_id, []),
        }
        rows.append(compact)
        market_counts[str(compact.get("country_code") or "unknown").upper()] += 1

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
        "source_kind": "production_postgresql_read_only",
        "production_fresh": True,
        "catalogue_max_updated_at": newest_update.isoformat() if newest_update else None,
        "privacy": {
            "queried_tables": ["hotels", "rate_plans"],
            "excluded_tables": [
                "conversation_logs",
                "search_sessions",
                "frontend_events",
                "bookings",
                "customers",
            ],
            "removed": ["address", "photos", "descriptions", "reviews", "order metrics"],
            "contains_customer_pii": False,
        },
        "hotels": len(rows),
        "rate_plans": len(rate_rows),
        "markets": dict(sorted(market_counts.items())),
        "output": output.name,
        "output_sha256": _sha256(output),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url-env", default="DATABASE_URL")
    parser.add_argument("--output", default=str(PACK / "fixtures/inventory_snapshot.jsonl.gz"))
    parser.add_argument(
        "--manifest", default=str(PACK / "fixtures/inventory_snapshot_manifest.json")
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    database_url = os.environ.get(args.database_url_env, "").strip()
    if not database_url:
        raise SystemExit(f"missing database URL in environment variable {args.database_url_env}")
    manifest = asyncio.run(
        export_prod_snapshot(database_url, Path(args.output), Path(args.manifest))
    )
    print(
        json.dumps(
            {
                "hotels": manifest["hotels"],
                "rate_plans": manifest["rate_plans"],
                "markets": len(manifest["markets"]),
                "output_sha256": manifest["output_sha256"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
