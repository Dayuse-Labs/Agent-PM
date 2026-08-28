#!/usr/bin/env python3
"""UX4 — does a real hotel in the live catalogue ever produce two MCP offers
whose DISPLAY SIGNATURE (offer_type, name, start_time, end_time, price)
collides completely, on the same day, under different `ratePlanUuid`s?

Why this exists (2026-08-27, chantier UX4). The
design decision (dedupe on the display signature, backend-side) is settled
and already covered by unit tests with synthetic offers
(`TestRatePlanDedupOnDisplaySignature` in `test_inline_tools.py`). What those
tests cannot answer is whether a real hotel in the live catalogue actually
triggers the case — the phase's own DoD requires either a real repro or an
honest "none found" in HANDOFF.md, never a claimed "proven in prod" without
one.

Method: `search_offers` across several markets/dates to collect real hotel
ids, then `get_hotel_details` each one and reproduce BOTH dedup passes
in-process for every day that hotel has offers on — the OLD one (offer_id
only) and the CURRENT one (`inline_tools._day_rate_plans`, offer_id +
display signature). A hit is a day where the two counts differ.

Deliberately NOT a pytest: real network calls to MCP_B2C. `pytest -q` must
stay offline (CLAUDE.md). Same posture as scripts/probe_currency_priceeuro.py.

Usage:
    set -a; . ./.env; set +a
    .venv/bin/python scripts/probe_rateplan_dedup.py
    .venv/bin/python scripts/probe_rateplan_dedup.py --cities 12 --size 20 --dates 2
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import os
import sys

_CONCIERGE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "agents", "b2c_concierge",
)
if _CONCIERGE not in sys.path:
    sys.path.insert(0, _CONCIERGE)

from b2c_concierge import inline_tools  # noqa: E402

#: A spread of French/European markets — day-use inventory is densest in
#: France (CLAUDE.md), so a same-hotel, same-day rate-plan collision is
#: likeliest to show up first there.
CITIES: tuple[dict[str, object], ...] = (
    {"label": "Paris", "lat": 48.8566, "lon": 2.3522},
    {"label": "Lyon", "lat": 45.7640, "lon": 4.8357},
    {"label": "Marseille", "lat": 43.2965, "lon": 5.3698},
    {"label": "Bordeaux", "lat": 44.8378, "lon": -0.5792},
    {"label": "Nice", "lat": 43.7102, "lon": 7.2620},
    {"label": "Toulouse", "lat": 43.6047, "lon": 1.4442},
    {"label": "Lille", "lat": 50.6292, "lon": 3.0573},
    {"label": "Nantes", "lat": 47.2184, "lon": -1.5536},
    {"label": "Strasbourg", "lat": 48.5734, "lon": 7.7521},
    {"label": "Madrid", "lat": 40.4168, "lon": -3.7038},
    {"label": "Barcelona", "lat": 41.3874, "lon": 2.1686},
    {"label": "Brussels", "lat": 50.8503, "lon": 4.3517},
    {"label": "Rome", "lat": 41.9028, "lon": 12.4964},
    {"label": "Milan", "lat": 45.4642, "lon": 9.1900},
    {"label": "Amsterdam", "lat": 52.3676, "lon": 4.9041},
    {"label": "Berlin", "lat": 52.5200, "lon": 13.4050},
    {"label": "Vienna", "lat": 48.2082, "lon": 16.3738},
    {"label": "Lisbon", "lat": 38.7223, "lon": -9.1393},
    {"label": "Geneva", "lat": 46.2044, "lon": 6.1432},
    {"label": "Munich", "lat": 48.1351, "lon": 11.5820},
    {"label": "London", "lat": 51.5074, "lon": -0.1278},
    {"label": "Bangkok", "lat": 13.7563, "lon": 100.5018},
    {"label": "New York", "lat": 40.7128, "lon": -74.0060},
    {"label": "Zurich", "lat": 47.3769, "lon": 8.5417},
    {"label": "Montpellier", "lat": 43.6108, "lon": 3.8767},
    {"label": "Rennes", "lat": 48.1173, "lon": -1.6778},
    {"label": "Reims", "lat": 49.2583, "lon": 4.0317},
    {"label": "Toulon", "lat": 43.1242, "lon": 5.9280},
    {"label": "Grenoble", "lat": 45.1885, "lon": 5.7245},
    {"label": "Dijon", "lat": 47.3220, "lon": 5.0415},
    {"label": "Angers", "lat": 47.4784, "lon": -0.5632},
    {"label": "Nimes", "lat": 43.8367, "lon": 4.3601},
)


def _dates(n: int) -> list[str]:
    today = datetime.date.today()
    return [(today + datetime.timedelta(days=i)).isoformat() for i in range(1, n + 1)]


def _old_dedup_plans(offers: list, date: str) -> list[dict]:
    """Reproduces the PRE-UX4 `_day_rate_plans` exactly: dedup by offer_id
    only (no display signature), same sort, same `_MAX_RATE_PLANS` cap — the
    cap must be replicated too, or a hotel with >6 genuinely distinct
    formulas reads as a false "collision" once the current code caps it."""
    plans: list[dict] = []
    seen: set[str] = set()
    for offer in inline_tools._offers_for_day(offers, date):
        plan = inline_tools._rate_plan_view(offer)
        if plan is None or plan["offer_id"] in seen:
            continue
        seen.add(plan["offer_id"])
        plans.append(plan)
    plans.sort(key=lambda p: (p.get("price_eur_cents") is None, p.get("price_eur_cents") or 0))
    return plans[: inline_tools._MAX_RATE_PLANS]


def _signature(plan: dict) -> tuple:
    return (
        plan.get("offer_type"),
        plan.get("name"),
        plan.get("start_time"),
        plan.get("end_time"),
        plan.get("price_eur_cents"),
    )


async def _probe_hotel(session, hotel_id: int) -> dict | None:
    details = await inline_tools._call_tool(session, "get_hotel_details", {"hotelId": hotel_id})
    if not details["ok"]:
        return None
    offers = details["data"].get("offers") or []
    days: list[str] = sorted(
        {
            o["availabilityDate"]
            for o in offers
            if isinstance(o, dict) and isinstance(o.get("availabilityDate"), str)
        }
    )
    for day in days:
        before_plans = _old_dedup_plans(offers, day)
        after_plans = inline_tools._day_rate_plans(offers, day)
        # A real hit is offer_ids that survived the OLD dedup but share a
        # display signature with another survivor — the cap alone (a hotel
        # with >6 genuinely distinct formulas) is not a collision.
        signatures = [_signature(p) for p in before_plans]
        if len(set(signatures)) < len(signatures):
            return {
                "hotel_id": hotel_id,
                "date": day,
                "before": len(before_plans),
                "after": len(after_plans),
                "offers_that_day": list(inline_tools._offers_for_day(offers, day)),
            }
    return None


async def main(n_cities: int, size: int, n_dates: int, delay: float, offset: int = 0) -> int:
    hotel_ids: dict[int, str] = {}
    for city in CITIES[offset : offset + n_cities]:
        for date in _dates(n_dates):
            # A fresh session per call, and a throttle between them: chained
            # calls on one session 429 quickly (memory: "MCP 429s on chained
            # calls") and a 429 tears the whole streamable-HTTP session down,
            # failing every call still queued on it.
            async with inline_tools._mcp_session() as session:
                search = await inline_tools._call_tool(
                    session,
                    "search_offers",
                    {"lat": city["lat"], "lon": city["lon"], "date": date, "size": size},
                )
            if not search["ok"]:
                print(f"  search failed {city['label']} {date}: {search.get('error')}")
                await asyncio.sleep(delay)
                continue
            for hotel in search["data"].get("results") or []:
                hid = hotel.get("hotelId")
                if isinstance(hid, int):
                    hotel_ids.setdefault(hid, str(city["label"]))
            await asyncio.sleep(delay)
    print(f"Collected {len(hotel_ids)} unique hotels across {n_cities} cities x {n_dates} date(s)")

    hits = []
    for i, (hotel_id, city_label) in enumerate(hotel_ids.items(), 1):
        async with inline_tools._mcp_session() as session:
            hit = await _probe_hotel(session, hotel_id)
        if hit:
            hit["city"] = city_label
            hits.append(hit)
            print(
                f"HIT #{len(hits)}: hotel {hotel_id} ({city_label}) on {hit['date']}: "
                f"before={hit['before']} after={hit['after']}"
            )
        if i % 25 == 0:
            print(f"  ...probed {i}/{len(hotel_ids)} hotels, {len(hits)} hit(s) so far")
        await asyncio.sleep(delay)

    print()
    print(f"Probed {len(hotel_ids)} hotels total. Hits: {len(hits)}")
    for hit in hits[:5]:
        print(
            f"  hotel_id={hit['hotel_id']} city={hit['city']} date={hit['date']} "
            f"before={hit['before']} after={hit['after']}"
        )
        for o in hit["offers_that_day"]:
            print(
                f"    uuid={o.get('ratePlanUuid')} type={o.get('offerType')} "
                f"name={o.get('ratePlanName')} "
                f"start={o.get('startHour')}:{o.get('startMinute', 0)} "
                f"end={o.get('endHour')}:{o.get('endMinute', 0)} price={o.get('priceEuro')}"
            )
    return 0 if hits else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cities", type=int, default=len(CITIES))
    parser.add_argument("--size", type=int, default=20)
    parser.add_argument("--dates", type=int, default=1)
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between MCP calls")
    parser.add_argument("--offset", type=int, default=0, help="skip the first N cities in CITIES")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.cities, args.size, args.dates, args.delay, args.offset)))
