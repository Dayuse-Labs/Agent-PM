#!/usr/bin/env python3
"""UX3 phase 1 — does MCP_B2C's `priceEuro` carry EUR, or the hotel's own
local currency under a misleading name?

Why this exists (2026-08-27). `b2c_concierge/inline_tools.py::_format_price_eur_cents`
admits it does not know: "MCP performs no conversion server-side (verified: a
hotel's priceEuro is identical whether its own currencyCode is EUR or
USD/GBP)". That sentence supports two readings ten times apart in cost
(display-only fix vs. a currency-conversion feature we don't have), so this
probe answers with numbers before any production code changes.

Method: call `search_offers` then `get_hotel_details` directly against
MCP_B2C for hotels in non-EUR markets, and print `priceEuro` next to
`currencyCode`. THB is the decisive case: ~1200 THB/night (~30 EUR) has no
overlap with ~3000 (30 EUR in cents) — whichever the number is closer to
answers the question on its own, no comparison needed.

Deliberately NOT a pytest: real network calls to MCP_B2C (paid backend).
`pytest -q` must stay offline (CLAUDE.md). Same posture as
scripts/probe_geo_landmarks.py.

Usage:
    set -a; . ./.env; set +a
    .venv/bin/python scripts/probe_currency_priceeuro.py
    .venv/bin/python scripts/probe_currency_priceeuro.py --json
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

from b2c_concierge import inline_tools  # noqa: E402
from b2c_common import build_hotel_page_url  # noqa: E402

#: city, lat, lon, market label — non-EUR markets from `_MARKET`
#: (libs/b2c_common/b2c_common/hotel_urls.py). THB is the decisive case:
#: its order of magnitude alone tells EUR from local currency apart.
CITIES: tuple[dict[str, object], ...] = (
    {"label": "Bangkok (TH, THB)", "lat": 13.7563, "lon": 100.5018},
    {"label": "New York (US, USD)", "lat": 40.7128, "lon": -74.0060},
    {"label": "London (GB, GBP)", "lat": 51.5074, "lon": -0.1278},
    {"label": "Zurich (CH, CHF)", "lat": 47.3769, "lon": 8.5417},
)


def _tomorrow() -> str:
    return (datetime.date.today() + datetime.timedelta(days=1)).isoformat()


async def _probe_city(city: dict[str, object], date: str) -> dict[str, object]:
    async with inline_tools._mcp_session() as session:
        search = await inline_tools._call_tool(
            session,
            "search_offers",
            {"lat": city["lat"], "lon": city["lon"], "date": date, "size": 5},
        )
        if not search["ok"]:
            return {"city": city["label"], "error": search.get("error")}

        results = search["data"].get("results") or []
        if not results:
            return {"city": city["label"], "error": "no results"}

        hotel = results[0]
        hotel_id = hotel.get("hotelId")

        details = await inline_tools._call_tool(
            session, "get_hotel_details", {"hotelId": hotel_id}
        )
        offers = []
        if details["ok"]:
            offers = details["data"].get("offers") or []

        url = build_hotel_page_url(
            hotel.get("slug"), hotel.get("countryCode"), hotel.get("countryName")
        )

        return {
            "city": city["label"],
            "hotel_id": hotel_id,
            "hotel_name": hotel.get("name"),
            "currency_code": hotel.get("currencyCode"),
            "country_name": hotel.get("countryName"),
            "slug": hotel.get("slug"),
            "public_url": url,
            "search_result_price_euro": hotel.get("offers", [{}])[0].get("priceEuro")
            if hotel.get("offers")
            else None,
            "detail_offers_price_euro": [o.get("priceEuro") for o in offers[:5]],
            "detail_offer_count": len(offers),
        }


async def _run(date: str) -> list[dict[str, object]]:
    out = []
    for city in CITIES:
        result = await _probe_city(city, date)
        out.append(result)
        # MCP_B2C 429s on chained calls (known repo trap) — space them out.
        await asyncio.sleep(2)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD, default tomorrow")
    args = parser.parse_args()

    date = args.date or _tomorrow()
    results = asyncio.run(_run(date))

    if args.json:
        print(json.dumps({"date": date, "results": results}, indent=2, ensure_ascii=False))
        return

    print(f"UX3 phase 1 — priceEuro probe, date={date}\n")
    for r in results:
        print(f"=== {r['city']} ===")
        if r.get("error"):
            print(f"  ERROR: {r['error']}")
            continue
        print(f"  hotel: {r['hotel_name']} (id={r['hotel_id']}, country={r['country_name']})")
        print(f"  currencyCode: {r['currency_code']}")
        print(f"  search_offers priceEuro (best): {r['search_result_price_euro']}")
        print(f"  get_hotel_details priceEuro (per offer): {r['detail_offers_price_euro']}")
        print(f"  public URL: {r['public_url']}")
        print()


if __name__ == "__main__":
    main()
