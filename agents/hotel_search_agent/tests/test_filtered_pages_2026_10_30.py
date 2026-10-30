"""A budget in another currency, and a page the code's filters thinned (2026-10-30).

Prod after #175 (100 real conversations): « Cheap hotel no more than £60 »
(London) → 0 card twice, MCP counting 233 offers; « spa in Paris under £100 »
→ 0 card in 4 turns; « Sunnyvale », an afternoon → 1 card of 5. MCP's
`priceRangeMax` is in EUR, so a pound budget never reached it, and the leaf
checked the 5 hotels of the first page afterwards.

Quotes below: MCP's shape, each offer's total in EUR cents and in the hotel's
own currency (minor units), at 1.17 EUR per GBP.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types as genai_types

from hotel_search_agent import budget_injection
from hotel_search_agent.budget_injection import inject_profile_budget
from hotel_search_agent.filter_pages import fill_filtered_page_after_tool
from hotel_search_agent.response_bridge import STATE_DAYPART_KEY, _STATE_RESULTS_KEY, capture_after_tool

RATE = 1.17


def _gbp_hotel(hotel_id: int, pounds: int) -> dict:
    return {
        "hotelId": hotel_id, "name": f"London {hotel_id}", "currencyCode": "GBP", "offers": [{
            "priceEuro": int(pounds * RATE * 100), "priceEuroWithBookingFees": int(pounds * RATE * 100),
            "hotelCurrency": "GBP", "hotelPrice": pounds * 100, "hotelPriceWithBookingFees": pounds * 100,
            "availabilityDate": "2026-10-30", "startHour": 10, "endHour": 17,
        }],
    }


def _eur_hotel(hotel_id: int, euros: int, start: int = 10, end: int = 17) -> dict:
    return {
        "hotelId": hotel_id, "name": f"Hotel {hotel_id}", "currencyCode": "EUR", "offers": [{
            "priceEuro": euros * 100, "priceEuroWithBookingFees": euros * 100, "hotelCurrency": "EUR",
            "hotelPrice": euros * 100, "hotelPriceWithBookingFees": euros * 100,
            "availabilityDate": "2026-10-30", "startHour": start, "endHour": end,
        }],
    }


PRICEY = [_gbp_hotel(i, 75 + 10 * i) for i in range(1, 6)]
CHEAP = [_gbp_hotel(10 + i, 45 + 3 * i) for i in range(1, 5)]


class _Search:
    name = "search_offers"

    def __init__(self, pages):
        self.pages, self.calls = pages, []

    async def run_async(self, *, args, tool_context):
        self.calls.append(dict(args))
        return {"structuredContent": self.pages(args)}


def _ctx(profile_in: dict) -> SimpleNamespace:
    datapart = a2a_types.Part(root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in}))
    parts = [genai_types.Part(text="x"), convert_a2a_part_to_genai_part(datapart)]
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


def _turn(tool: _Search, ctx: SimpleNamespace, args: dict) -> list[dict]:
    async def flow():
        inject_profile_budget(tool, args, ctx)
        response = await tool.run_async(args=args, tool_context=ctx)
        await fill_filtered_page_after_tool(tool, args, ctx, response)
        capture_after_tool(tool, args, ctx, response)
    asyncio.run(flow())
    return ctx.state[_STATE_RESULTS_KEY]


@pytest.fixture(autouse=True)
def _no_rate_learnt(monkeypatch):
    monkeypatch.setattr(budget_injection, "_RATES", {})


GBP_60 = {"requested_budget": {"amount": 60, "currency": "GBP", "unit": "total"}}


def test_a_pound_budget_runs_again_with_its_cap_converted_at_mcps_rate():
    tool = _Search(lambda args: {"total": 4 if "priceRangeMax" in args else 233,
                                 "results": CHEAP if "priceRangeMax" in args else PRICEY})
    cards = _turn(tool, _ctx(GBP_60), {"lat": 51.5, "lon": -0.12, "date": "2026-10-30", "from": 0})

    assert len(tool.calls) == 2
    cap = tool.calls[1]["priceRangeMax"]
    assert 60 * RATE <= cap <= 60 * RATE * 1.03
    assert [card["name"] for card in cards] == [h["name"] for h in CHEAP]
    assert all(card["hotel_price_minor"] <= 6000 for card in cards)


def test_once_the_rate_is_known_the_cap_reaches_mcp_on_the_first_call():
    budget_injection.learn_rates({"results": PRICEY})
    tool = _Search(lambda args: {"total": 4, "results": CHEAP if "priceRangeMax" in args else PRICEY})
    cards = _turn(tool, _ctx(GBP_60), {"lat": 51.5, "lon": -0.12, "date": "2026-10-30", "from": 0})

    assert len(tool.calls) == 1 and "priceRangeMax" in tool.calls[0]
    assert len(cards) == 4


def test_a_pound_budget_checks_hotels_quoted_in_euros_at_mcps_rate():
    """Paris, under £100: no hotel quotes pounds. At 1.17, £100 is €117."""
    budget_injection.learn_rates({"results": PRICEY})
    paris = [_eur_hotel(1, 140), _eur_hotel(2, 110), _eur_hotel(3, 95), _eur_hotel(4, 118)]
    tool = _Search(lambda args: {"total": 4, "results": paris})
    profile = {"requested_budget": {"amount": 100, "currency": "GBP", "unit": "total"}}
    cards = _turn(tool, _ctx(profile), {"lat": 48.85, "lon": 2.35, "date": "2026-10-30", "from": 0})

    assert {card["name"] for card in cards} == {"Hotel 2", "Hotel 3"}


def test_a_part_of_the_day_that_thins_the_page_fetches_the_next_pages():
    """Sunnyvale, this afternoon: one hotel of the page covers it."""
    page = [_eur_hotel(1, 90, 13, 23), *(_eur_hotel(i, 90, 8, 12) for i in range(2, 6))]
    later = {5: [_eur_hotel(i, 90, 12, 18) for i in range(6, 11)], 10: [_eur_hotel(i, 90, 9, 11) for i in range(11, 16)]}
    tool = _Search(lambda args: {"total": 30, "results": page if not args.get("from") else later[args["from"]]})
    ctx = _ctx({})
    ctx.state[STATE_DAYPART_KEY] = "afternoon"
    cards = _turn(tool, ctx, {"lat": 37.37, "lon": -122.03, "date": "2026-10-30", "from": 0})

    assert sorted(call.get("from") for call in tool.calls) == [0, 5, 10]
    assert len(cards) == 5


def test_nothing_filtering_the_cards_makes_no_extra_call():
    tool = _Search(lambda args: {"total": 233, "results": PRICEY[:2]})
    _turn(tool, _ctx({}), {"lat": 51.5, "lon": -0.12, "date": "2026-10-30", "from": 0})
    assert len(tool.calls) == 1


def test_a_full_page_after_the_filters_makes_no_extra_call():
    tool = _Search(lambda args: {"total": 233, "results": CHEAP + [_gbp_hotel(30, 50)]})
    _turn(tool, _ctx(GBP_60), {"lat": 51.5, "lon": -0.12, "date": "2026-10-30", "from": 0})
    assert len(tool.calls) == 1
