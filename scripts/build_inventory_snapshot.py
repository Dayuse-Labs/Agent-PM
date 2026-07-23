#!/usr/bin/env python3
"""Build the static Dayuse inventory-density snapshot for the geo resolver (S-G3, A1-a).

The geo resolver (`hotel_search_agent.geo_resolver`) demotes a geocoding
candidate that has ZERO bookable Dayuse hotels near it below any candidate that
has some — the single signal that kills "Lisbon, Arkansas" and the Victoria
homonyms that a raw geocoder ranks by prominence alone (see
`reports/research/geo-disambiguation-memo.md` §B/§C). To answer "how many
hotels near this lat/lon?" deterministically and with zero runtime dependency
(arbitration A1-a: static snapshot, provider swappable — a live MCP counter is
A1-c, deferred), we compile every hotel's coordinate into a small JSON the leaf
ships with.

Source = the `structured_hotels_<cc>.json` market exports (8 701 hotels /
29 markets), the SAME exports the eval fixture is built from — NOT `baseline/`
(raw user messages, RGPD-forbidden, never read here). Each record carries
`latitude`/`longitude`; we keep ONLY the coordinate (no name, address, price,
or any hotel attribute) — a density snapshot, not a hotel catalogue.

The output is deterministic given its inputs (points sorted, coordinates rounded,
the "export date" derived from the source files' modification time, never a
wall clock) so a regeneration is a reviewable, byte-stable diff. Refresh is
manual and documented (run this script; commit the diff) — the catalogue is
stable per S-A, so staleness is acceptable for v1.

Usage:
    python scripts/build_inventory_snapshot.py \\
        --source-dir ~/Projects/agent-usa/data \\
        --out agents/hotel_search_agent/hotel_search_agent/data/inventory_snapshot.json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import os
from typing import Any

SCHEMA_VERSION = "1.0"
COORD_PRECISION_DECIMALS = 5  # ~1.1 m — far finer than any density radius; keeps points distinct


def extract_points(records: list[dict[str, Any]]) -> list[list[float]]:
    """`[lat, lon]` for every record with a usable coordinate; garbage/absent
    coordinates are skipped (never a fabricated 0,0). Rounded for a compact,
    stable file — precision is irrelevant to a kilometre-scale density count."""
    points: list[list[float]] = []
    for rec in records:
        lat = rec.get("latitude")
        lon = rec.get("longitude")
        try:
            latf = float(lat)  # type: ignore[arg-type]
            lonf = float(lon)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if not (-90.0 <= latf <= 90.0 and -180.0 <= lonf <= 180.0):
            continue
        if latf == 0.0 and lonf == 0.0:  # null-island: a missing coord, not a real hotel
            continue
        points.append([round(latf, COORD_PRECISION_DECIMALS), round(lonf, COORD_PRECISION_DECIMALS)])
    return points


def build_snapshot(
    markets: dict[str, list[dict[str, Any]]], *, source_export_date: str
) -> dict[str, Any]:
    """Assemble the snapshot dict from `{market_code: [hotel_records]}`.

    Deterministic: markets sorted, points sorted (order carries no meaning — we
    only ever COUNT points in a radius). `hotel_count` is the number of points
    kept (records without a usable coordinate contribute to no density and are
    dropped), so it can be < the raw export row count."""
    per_market_counts: dict[str, int] = {}
    all_points: list[list[float]] = []
    for market in sorted(markets):
        pts = extract_points(markets[market])
        per_market_counts[market.upper()] = len(pts)
        all_points.extend(pts)
    all_points.sort()
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "dayuse_inventory_density_snapshot",
        "generated_from": "structured_hotels_<cc>.json (agent-usa market exports, same source as the eval fixture)",
        "source_export_date": source_export_date,
        "coord_precision_decimals": COORD_PRECISION_DECIMALS,
        "hotel_count": len(all_points),
        "markets": per_market_counts,
        "points": all_points,
    }


def _load_market_files(source_dir: str) -> tuple[dict[str, list[dict[str, Any]]], str]:
    """Read every `structured_hotels_<cc>.json` in `source_dir`. Returns the
    records keyed by market code, plus an export date derived from the newest
    source file's mtime (deterministic, never a wall clock)."""
    pattern = os.path.join(os.path.expanduser(source_dir), "structured_hotels_*.json")
    paths = sorted(glob.glob(pattern))
    # Exclude the "_enriched" variant — a different, larger export, not a market file.
    paths = [p for p in paths if "_enriched" not in os.path.basename(p)]
    if not paths:
        raise SystemExit(f"No structured_hotels_*.json under {source_dir!r}")
    markets: dict[str, list[dict[str, Any]]] = {}
    newest_mtime = 0.0
    for path in paths:
        base = os.path.basename(path)
        code = base[len("structured_hotels_") : -len(".json")]
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        markets[code] = data if isinstance(data, list) else list(data.values())
        newest_mtime = max(newest_mtime, os.path.getmtime(path))
    export_date = _dt.datetime.fromtimestamp(newest_mtime, tz=_dt.timezone.utc).date().isoformat()
    return markets, export_date


def main() -> None:
    default_out = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "agents",
        "hotel_search_agent",
        "hotel_search_agent",
        "data",
        "inventory_snapshot.json",
    )
    parser = argparse.ArgumentParser(description="Build the geo-resolver inventory-density snapshot.")
    parser.add_argument(
        "--source-dir",
        default="~/Projects/agent-usa/data",
        help="Directory holding structured_hotels_<cc>.json market exports (NOT baseline/).",
    )
    parser.add_argument("--out", default=default_out, help="Output snapshot JSON path.")
    args = parser.parse_args()

    markets, export_date = _load_market_files(args.source_dir)
    snapshot = build_snapshot(markets, source_export_date=export_date)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
        fh.write("\n")
    print(
        f"Wrote {snapshot['hotel_count']} points across {len(snapshot['markets'])} markets "
        f"(export {export_date}) → {args.out}"
    )


if __name__ == "__main__":
    main()
