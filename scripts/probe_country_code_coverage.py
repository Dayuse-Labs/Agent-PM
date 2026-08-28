#!/usr/bin/env python3
"""UX6 — is `_ISO_BY_COUNTRY_NAME` (hotel_urls.py:57) still on the hot path?

Why this exists (2026-08-28). `_ISO_BY_COUNTRY_NAME` is a 25-line hand-kept
country-name → ISO2 table whose docstring dates its own reason: "search_offers
sends `countryName`, never an ISO code (probed 2026-07-20)". Both callers of
`build_hotel_page_url` already pass `countryCode` FIRST
(`inline_tools.py:318`, `response_bridge.py:574`), so if MCP_B2C now sends a
usable `countryCode` on every hotel, the name table is a dead fallback.
`response_bridge.py:562-565` still asserts the opposite ("search_offers
doesn't send one today") — one of the two statements is stale, and only a
live measurement says which.

What is measured, per hotel, on BOTH payload shapes that reach the builder:
  - `search_offers` results   → the leaf's card path (response_bridge)
  - `get_hotel_details`       → the concierge's inline path (inline_tools)
and for each: does `countryCode` resolve a market ALONE (leg 1 of
`_resolve_market`), does `countryName` resolve one alone (leg 2), and do the
two agree. A market resolved by leg 1 makes leg 2 unreachable for that hotel.

Sampling: several markets deliberately, including non-euro ones — the trap
this probe exists to avoid is concluding from FR alone that a field is
reliable everywhere (`countryCode` could be an FR-only artifact).

Deliberately NOT a pytest: real network calls to MCP_B2C. `pytest -q` stays
offline (CLAUDE.md). Same posture as scripts/probe_currency_priceeuro.py.

Usage:
    set -a; . ./.env; set +a
    .venv/bin/python scripts/probe_country_code_coverage.py
    .venv/bin/python scripts/probe_country_code_coverage.py --json
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys

_CONCIERGE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "agents", "b2c_concierge",
)
if _CONCIERGE not in sys.path:
    sys.path.insert(0, _CONCIERGE)

from b2c_common import hotel_urls  # noqa: E402
from b2c_concierge import inline_tools  # noqa: E402

#: Markets to sample. `euro` is bookkeeping only — the phase requires >= 4
#: countries with >= 1 non-euro, so the split must be visible in the output.
MARKETS: tuple[dict[str, object], ...] = (
    {"iso": "FR", "label": "Paris", "lat": 48.8566, "lon": 2.3522, "euro": True},
    {"iso": "ES", "label": "Madrid", "lat": 40.4168, "lon": -3.7038, "euro": True},
    {"iso": "IT", "label": "Milan", "lat": 45.4642, "lon": 9.1900, "euro": True},
    {"iso": "DE", "label": "Berlin", "lat": 52.5200, "lon": 13.4050, "euro": True},
    {"iso": "GB", "label": "London", "lat": 51.5074, "lon": -0.1278, "euro": False},
    {"iso": "US", "label": "New York", "lat": 40.7128, "lon": -74.0060, "euro": False},
    {"iso": "CH", "label": "Zurich", "lat": 47.3769, "lon": 8.5417, "euro": False},
    {"iso": "TH", "label": "Bangkok", "lat": 13.7563, "lon": 100.5018, "euro": False},
)

#: --coverage: the OTHER question about `_ISO_BY_COUNTRY_NAME`. If the name
#: table is the load-bearing leg, then a market whose `countryName` it does not
#: contain silently loses every hotel URL. So sweep the remaining `_MARKET`
#: entries (the 8 above already cover FR/ES/IT/DE/GB/US/CH/TH) plus two
#: DELIBERATELY unmapped countries, to see the honest-None path too.
COVERAGE_MARKETS: tuple[dict[str, object], ...] = (
    {"iso": "NL", "label": "Amsterdam", "lat": 52.3676, "lon": 4.9041, "euro": True},
    {"iso": "BE", "label": "Brussels", "lat": 50.8503, "lon": 4.3517, "euro": True},
    {"iso": "AT", "label": "Vienna", "lat": 48.2082, "lon": 16.3738, "euro": True},
    {"iso": "IE", "label": "Dublin", "lat": 53.3498, "lon": -6.2603, "euro": True},
    {"iso": "PT", "label": "Lisbon", "lat": 38.7223, "lon": -9.1393, "euro": True},
    {"iso": "SE", "label": "Stockholm", "lat": 59.3293, "lon": 18.0686, "euro": False},
    {"iso": "SG", "label": "Singapore", "lat": 1.3521, "lon": 103.8198, "euro": False},
    {"iso": "HK", "label": "Hong Kong", "lat": 22.3193, "lon": 114.1694, "euro": False},
    {"iso": "AE", "label": "Dubai", "lat": 25.2048, "lon": 55.2708, "euro": False},
    {"iso": "BR", "label": "Sao Paulo", "lat": -23.5505, "lon": -46.6333, "euro": False},
    {"iso": "AU", "label": "Sydney", "lat": -33.8688, "lon": 151.2093, "euro": False},
    {"iso": "CA", "label": "Toronto", "lat": 43.6532, "lon": -79.3832, "euro": False},
    {"iso": "NZ", "label": "Auckland", "lat": -36.8485, "lon": 174.7633, "euro": False},
    {"iso": "MY", "label": "Kuala Lumpur", "lat": 3.1390, "lon": 101.6869, "euro": False},
    # Not in `_MARKET` on purpose: the expected outcome is no URL at all, which
    # is the module's documented honest behaviour, not a bug.
    {"iso": "JP*", "label": "Tokyo", "lat": 35.6762, "lon": 139.6503, "euro": False},
    {"iso": "MX*", "label": "Mexico City", "lat": 19.4326, "lon": -99.1332, "euro": False},
)

#: Per-market page size. 10 is enough to see a field that is either always or
#: never projected, and keeps the call count low (MCP_B2C 429s on chained calls).
SIZE = 10

#: How many hotels per market also get a `get_hotel_details` round-trip. The
#: two payloads are built by different MCP projections, so the field can be
#: present on one and absent on the other — but details is 1 call per hotel,
#: hence a small sample.
DETAILS_PER_MARKET = 3


def _resolves_by_code(country_code: object) -> bool:
    """Leg 1 of `hotel_urls._resolve_market`, in isolation."""
    return hotel_urls._resolve_market(country_code, None) is not None


def _resolves_by_name(country_name: object) -> bool:
    """Leg 2 of `hotel_urls._resolve_market`, in isolation."""
    return hotel_urls._resolve_market(None, country_name) is not None


def _observe(hotel: dict, source: str) -> dict[str, object]:
    code = hotel.get("countryCode")
    name = hotel.get("countryName") or hotel.get("country")
    by_code = _resolves_by_code(code)
    by_name = _resolves_by_name(name)
    market_code = hotel_urls._resolve_market(code, None)
    market_name = hotel_urls._resolve_market(None, name)
    return {
        "source": source,
        "hotel_id": hotel.get("hotelId") or hotel.get("id"),
        "raw_country_code": code,
        "raw_country_name": name,
        "code_present": isinstance(code, str) and bool(code.strip()),
        "name_present": isinstance(name, str) and bool(name.strip()),
        "resolves_by_code": by_code,
        "resolves_by_name": by_name,
        # The only case that keeps `_ISO_BY_COUNTRY_NAME` alive: the code leg
        # fails and the name leg saves the URL.
        "name_leg_load_bearing": (not by_code) and by_name,
        "legs_disagree": by_code and by_name and market_code != market_name,
        "no_market_at_all": not (by_code or by_name),
        "slug_present": isinstance(hotel.get("slug"), str) and bool(hotel.get("slug")),
    }


async def _probe_market(market: dict[str, object], date: str) -> dict[str, object]:
    observations: list[dict[str, object]] = []
    error: str | None = None

    async with inline_tools._mcp_session() as session:
        search = await inline_tools._call_tool(
            session,
            "search_offers",
            {"lat": market["lat"], "lon": market["lon"], "date": date, "size": SIZE},
        )
        if not search["ok"]:
            return {"market": market, "error": str(search.get("error")), "observations": []}
        results = search["data"].get("results") or []
        total = search["data"].get("total")
        if not results:
            # Distinguish "no inventory" from "all offers past today's cutoff"
            # (repo trap: total > 0 with results == [] means cutoff, not empty).
            error = f"no results (total={total})"
        for hotel in results:
            if isinstance(hotel, dict):
                observations.append(_observe(hotel, "search_offers"))

    detail_ids = [
        obs["hotel_id"] for obs in observations[:DETAILS_PER_MARKET] if obs["hotel_id"]
    ]
    for hotel_id in detail_ids:
        # A fresh session per call: a 429 on one detail call must not poison
        # the rest of the queue (lesson from probe_rateplan_dedup.py).
        await asyncio.sleep(1.5)
        async with inline_tools._mcp_session() as session:
            details = await inline_tools._call_tool(
                session, "get_hotel_details", {"hotelId": hotel_id}
            )
        if not details["ok"]:
            continue
        payload = details["data"]
        hotel = payload.get("hotel") if isinstance(payload.get("hotel"), dict) else payload
        if isinstance(hotel, dict):
            observations.append(_observe(hotel, "get_hotel_details"))

    return {"market": market, "error": error, "observations": observations}


async def _run(date: str, markets: tuple[dict[str, object], ...], details: int) -> list[dict[str, object]]:
    global DETAILS_PER_MARKET
    DETAILS_PER_MARKET = details
    out = []
    for market in markets:
        out.append(await _probe_market(market, date))
        # MCP_B2C 429s on chained calls (known repo trap) — space the markets out.
        await asyncio.sleep(2)
    return out


def _summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    flat = [obs for row in rows for obs in row["observations"]]
    by_source: dict[str, list[dict[str, object]]] = {}
    for obs in flat:
        by_source.setdefault(str(obs["source"]), []).append(obs)
    summary: dict[str, object] = {}
    for source, group in by_source.items():
        n = len(group)
        summary[source] = {
            "hotels": n,
            "code_resolves_market": sum(1 for o in group if o["resolves_by_code"]),
            "name_resolves_market": sum(1 for o in group if o["resolves_by_name"]),
            "name_leg_load_bearing": sum(1 for o in group if o["name_leg_load_bearing"]),
            "legs_disagree": sum(1 for o in group if o["legs_disagree"]),
            "no_market_at_all": sum(1 for o in group if o["no_market_at_all"]),
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD, default J+2")
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="sweep the remaining _MARKET entries (+2 unmapped) for countryName coverage",
    )
    args = parser.parse_args()

    date = args.date or (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
    markets = COVERAGE_MARKETS if args.coverage else MARKETS
    rows = asyncio.run(_run(date, markets, 0 if args.coverage else DETAILS_PER_MARKET))

    if args.json:
        print(json.dumps({"date": date, "rows": rows, "summary": _summarize(rows)}, indent=2, default=str))
        return

    print(f"date={date}  markets={len(markets)}")
    print()
    header = f"{'market':<14}{'src':<18}{'n':>4}{'byCode':>8}{'byName':>8}{'nameLB':>8}{'noMkt':>7}  sample countryCode / countryName"
    print(header)
    print("-" * len(header))
    for row in rows:
        market = row["market"]
        label = f"{market['iso']} {market['label']}"
        if row.get("error"):
            print(f"{label:<14}{'ERROR':<18}{row['error']}")
        for source in ("search_offers", "get_hotel_details"):
            group = [o for o in row["observations"] if o["source"] == source]
            if not group:
                continue
            sample = group[0]
            print(
                f"{label:<14}{source:<18}{len(group):>4}"
                f"{sum(1 for o in group if o['resolves_by_code']):>8}"
                f"{sum(1 for o in group if o['resolves_by_name']):>8}"
                f"{sum(1 for o in group if o['name_leg_load_bearing']):>8}"
                f"{sum(1 for o in group if o['no_market_at_all']):>7}"
                f"  {sample['raw_country_code']!r} / {sample['raw_country_name']!r}"
            )
    print()
    print("TOTALS")
    for source, stats in _summarize(rows).items():
        print(f"  {source}: {stats}")
    print()
    print("byCode = countryCode alone resolves a market (leg 1 of _resolve_market)")
    print("byName = countryName alone resolves a market (leg 2, _ISO_BY_COUNTRY_NAME)")
    print("nameLB = name leg LOAD-BEARING: code leg failed AND name leg saved the URL")


if __name__ == "__main__":
    main()
