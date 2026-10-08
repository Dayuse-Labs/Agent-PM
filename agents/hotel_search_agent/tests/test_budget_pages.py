"""Native-currency caps must not mistake one expensive page for no matches."""
import asyncio

import pytest
from types import SimpleNamespace

from hotel_search_agent.agent import root_agent
from hotel_search_agent.response_bridge import normalize_search_results, read_structured_payload
from hotel_search_agent.tool_budget_guard import make_per_tool_budget_callback

from .test_budget_injection import _ctx_with_profile


def hotel(i, price):
    return {'hotelId': i, 'name': f'Hotel {i}', 'currencyCode': 'AED', 'offers': [{
        'ratePlanUuid': f'offer-{i}', 'availabilityDate': '2026-10-08',
        'priceEuro': price // 4, 'priceEuroWithBookingFees': price // 4,
        'hotelCurrency': 'AED', 'hotelPrice': price, 'hotelPriceWithBookingFees': price,
        'startHour': 7, 'endHour': 13,
    }]}


class PagedTool:
    name = 'search_offers'
    def __init__(self, first=None, second=None):
        self.calls = []
        self.first = first if first is not None else [hotel(i, 20000) for i in range(5)]
        self.second = second if second is not None else [hotel(9, 13525)]
    async def run_async(self, *, args, tool_context):
        self.calls.append(dict(args))
        return {'structuredContent': {'resolvedDate': args['date'], 'total': 18,
            'results': self.first if args['from'] == 0 else self.second,
            'has_more': True, 'next_offset': args['from'] + 5}}


def run_callbacks(tool, ctx, args):
    async def run():
        # Exercise the production callback added after all argument guards.
        callbacks = root_agent.before_tool_callback
        callback = next((c for c in callbacks if c.__name__ == 'search_budget_pages_before_tool'), None)
        result = callback(tool, args, ctx) if callback else None
        if hasattr(result, '__await__'):
            result = await result
        if result is None:
            result = await tool.run_async(args=args, tool_context=ctx)
        return result
    return asyncio.run(run())


def context(limit=2):
    ctx = _ctx_with_profile(requested_budget={'amount': 150, 'currency': 'AED', 'unit': 'total'})
    ctx.invocation_id = 'one-turn'
    guard = make_per_tool_budget_callback({'search_offers': limit}, 2)
    assert guard(SimpleNamespace(name='search_offers'), {}, ctx) is None
    return ctx, guard


def test_native_budget_finds_next_page_without_relaxing_query_or_budget():
    ctx, guard = context()
    tool = PagedTool()
    args = {'lat': 25.07, 'lon': 55.12, 'date': '2026-10-08', 'from': 0,
            'timeSlot': {'startHour': 9}, 'sortBy': 'distance'}
    raw = run_callbacks(tool, ctx, args)
    cap = {'amount': 150, 'currency': 'AED', 'unit': 'total'}
    cards = normalize_search_results(read_structured_payload(raw), requested_budget=cap)
    assert [h['hotel_id'] for h in cards] == [9]
    assert len(tool.calls) == 2
    assert tool.calls[1] == {**tool.calls[0], 'from': 5}
    assert tool.calls[0]['size'] == 5
    assert guard(tool, args, ctx)['ok'] is False


@pytest.mark.parametrize("first,limit,extra", [
    ([hotel(3, 14000)], 2, {}),
    ([], 2, {}),
    (None, 1, {}),
    (None, 2, {"has_more": False}),
    (None, 2, {"next_offset": 10}),
    (None, 2, {"next_offset": True}),
])
def test_no_unnecessary_or_unbudgeted_extra_read(first, limit, extra):
    ctx, _ = context(limit)
    tool = PagedTool(first=first)
    original = tool.run_async
    async def adjusted(**kw):
        result = await original(**kw)
        result['structuredContent'].update(extra)
        return result
    tool.run_async = adjusted
    run_callbacks(tool, ctx, {'date': '2026-10-08', 'from': 0})
    assert len(tool.calls) == 1


def test_second_page_failure_is_not_reported_as_no_affordable_inventory():
    ctx, _ = context()
    tool = PagedTool()
    original = tool.run_async
    async def failing(**kw):
        result = await original(**kw)
        return result if len(tool.calls) == 1 else {'isError': True, 'error': 'upstream unavailable'}
    tool.run_async = failing
    result = run_callbacks(tool, ctx, {'date': '2026-10-08', 'from': 0})
    assert result['isError'] is True
    assert len(tool.calls) == 2


def test_cannot_merge_pages_from_different_dates():
    ctx, _ = context()
    tool = PagedTool()
    original = tool.run_async
    async def changed(**kw):
        result = await original(**kw)
        if len(tool.calls) == 2:
            result['structuredContent']['resolvedDate'] = '2026-10-09'
        return result
    tool.run_async = changed
    result = run_callbacks(tool, ctx, {'date': '2026-10-08', 'from': 0})
    assert result['ok'] is False
    assert len(tool.calls) == 2


def test_reservation_does_not_create_new_quota():
    from hotel_search_agent.tool_budget_guard import reserve_additional_call
    ctx = _ctx_with_profile()
    ctx.invocation_id = 'no-initial-call'
    assert reserve_additional_call(ctx, 'search_offers') is False
    ctx, guard = context()
    assert reserve_additional_call(ctx, 'search_offers') is True
    assert reserve_additional_call(ctx, 'search_offers') is False
    ctx.invocation_id = 'next-turn'
    assert reserve_additional_call(ctx, 'search_offers') is False
    assert guard(SimpleNamespace(name='search_offers'), {}, ctx) is None
    assert reserve_additional_call(ctx, 'search_offers') is True


def test_area_batch_keeps_its_existing_retrieval_owner():
    from hotel_search_agent.area_scope import STATE_AREAS
    from hotel_search_agent.budget_pages import search_budget_pages_before_tool
    ctx, _ = context()
    ctx.state[STATE_AREAS] = [{'latitude': 1, 'longitude': 2}]
    assert search_budget_pages_before_tool(PagedTool(), {}, ctx) is None
