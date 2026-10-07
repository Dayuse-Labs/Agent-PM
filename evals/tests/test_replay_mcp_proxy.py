import asyncio
import json

import pytest

from evals.replay_mcp_proxy import FixtureProxy, restore_dates, shift_request


def test_shift_preserves_relative_days_and_maps_structured_dates_back():
    args, days = shift_request("search_offers", {"date": "2026-07-04"}, "2026-07-03", "2026-10-08")
    assert args["date"] == "2026-10-09"
    result = restore_dates({"resolvedDate": "2026-10-09", "offers": [{"date": "2026-10-09"}],
                            "updatedAt": "2026-10-01"}, days)
    assert result == {"resolvedDate": "2026-07-04", "offers": [{"date": "2026-07-04"}], "updatedAt": "2026-10-01"}


def test_real_offer_calendar_fields_and_cutoff_move_together_but_article_freshness_does_not():
    _, days = shift_request("search_offers", {"date": "2026-07-04"}, "2026-07-03", "2026-10-08")
    result = restore_dates({"resolvedDate": "2026-10-09", "offers": [
        {"availabilityDate": "2026-10-09", "cutoffDeadlineUtc": "2026-10-09T16:00:00.000Z"}],
        "updatedAt": "2026-06-01T00:00:00Z"}, days)
    assert result["offers"] == [{"availabilityDate": "2026-07-04", "cutoffDeadlineUtc": "2026-07-04T16:00:00.000Z"}]
    assert result["resolvedDate"] == "2026-07-04"
    assert result["updatedAt"] == "2026-06-01T00:00:00Z"


def test_calendar_mapping_reaches_the_actual_hotel_card_and_booking_date():
    from hotel_search_agent.response_bridge import normalize_hotel

    _, days = shift_request("search_offers", {"date": "2026-07-04"}, "2026-07-03", "2026-10-08")
    hotel = {"hotelId": 1, "name": "Fixture hotel", "offers": [
        {"availabilityDate": "2026-10-09", "cutoffDeadlineUtc": "2026-10-09T16:00:00.000Z",
         "ratePlanUuid": "fixture-plan", "priceEuro": 6000, "startHour": 10, "startMinute": 0,
         "endHour": 17, "endMinute": 0}]}
    card = normalize_hotel(restore_dates(hotel, days))
    assert card["offer_date"] == "2026-07-04"
    assert card["offer_id"] == "fixture-plan"
    assert card["price_eur_cents"] == 6000


def test_undated_details_preserve_upcoming_contract_and_use_captured_reference_day(tmp_path):
    import hashlib

    async def run():
        proxy = FixtureProxy("https://example.invalid/mcp", "fake", tmp_path, "2026-10-08")
        args = {"hotelId": 1}
        key = hashlib.sha256(json.dumps([proxy.upstream, proxy.inventory_day, "get_hotel_details", args], sort_keys=True).encode()).hexdigest()
        body = {"offers": [{"availabilityDate": "2026-10-06"}, {"availabilityDate": "2026-10-07"}],
                "hasMoreUpcomingOffers": True}
        cached = {"result": {"structuredContent": body, "content": [{"type": "text", "text": json.dumps(body)}]},
                  "captured_at": "2026-10-06T12:00:00+00:00"}
        (tmp_path / (key + ".json")).write_text(json.dumps(cached))
        result = await proxy.tool("get_hotel_details", args, "2026-07-03")
        assert [o["availabilityDate"] for o in result["structuredContent"]["offers"]] == ["2026-07-03", "2026-07-04"]
        assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
        assert result["structuredContent"]["hasMoreUpcomingOffers"] is True
        assert json.loads((tmp_path / (key + ".json")).read_text()) == cached
        await proxy.client.aclose()
    asyncio.run(run())


def test_calendar_receipts_exclude_arguments_and_unlisted_context(tmp_path):
    import httpx
    from starlette.applications import Starlette
    from starlette.routing import Route

    async def run():
        receipts = tmp_path / "receipts.jsonl"
        proxy = FixtureProxy("https://example.invalid", "private-token", tmp_path / "cache", "2026-10-08", receipts)
        async def tool(*args):
            return {"structuredContent": {"private_body": "not for receipt"}}
        proxy.tool = tool
        app = Starlette(routes=[Route("/mcp", proxy.handle, methods=["POST"])])
        context = {"x-replay-case": "case", "x-replay-turn": "1", "x-replay-variant": "v",
                   "x-replay-session-id": "synthetic-session", "unlisted": "private-context"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost") as client:
            await client.post("/mcp", json={"id": 1, "method": "tools/call", "params": {
                "name": "get_hotel_details", "arguments": {"hotelId": 123}, "_meta": {"dayuse_replay": context}}})
        assert json.loads(receipts.read_text()) == {k: v for k, v in context.items() if k != "unlisted"} | {
            "tool": "get_hotel_details", "calendar_mapping_version": 2, "date_mode": "upcoming_snapshot"}
        assert receipts.stat().st_mode & 0o777 == 0o600
        await proxy.client.aclose()
    asyncio.run(run())


@pytest.mark.parametrize("tool", ["get_hotel_details", "compare_hotels", "generate_booking_link"])
def test_inline_tools_share_the_same_inventory_day_as_search(tool):
    args, days = shift_request(tool, {"date": "2026-07-04", "hotelId": 1}, "2026-07-03", "2026-10-08")
    assert args == {"date": "2026-10-09", "hotelId": 1}
    result = restore_dates({"url": "https://www.dayuse.fr/booking?checkinDate=2026-10-09&hotelId=1", "date": "2026-10-09"}, days)
    assert result == {"url": "https://www.dayuse.fr/booking?checkinDate=2026-07-04&hotelId=1", "date": "2026-07-04"}


def test_two_historical_clocks_share_equivalent_supply_without_response_mutation(tmp_path):
    async def run():
        proxy = FixtureProxy("https://example.invalid/mcp", "fake", tmp_path, "2026-10-08")
        calls = []

        async def rpc(method, params):
            calls.append(params)
            return {"result": {"structuredContent": {"resolvedDate": params["arguments"]["date"]},
                "content": [{"type": "text", "text": json.dumps({"resolvedDate": params["arguments"]["date"]})}]}}

        proxy.rpc = rpc
        first = await proxy.tool("search_offers", {"date": "2026-07-04"}, "2026-07-03")
        second = await proxy.tool("search_offers", {"date": "2026-08-04"}, "2026-08-03")
        assert len(calls) == 1
        assert first["structuredContent"]["resolvedDate"] == "2026-07-04"
        assert second["structuredContent"]["resolvedDate"] == "2026-08-04"
        cached = json.loads(next(tmp_path.glob("*.json")).read_text())
        assert cached["result"]["structuredContent"]["resolvedDate"] == "2026-10-09"
        await proxy.client.aclose()

    asyncio.run(run())


def test_cancellation_tool_cannot_reach_network(tmp_path):
    async def run():
        proxy = FixtureProxy("https://example.invalid", "fake", tmp_path, "2026-10-08")
        with pytest.raises(ValueError, match="allowlist"):
            await proxy.tool("cancel_booking", {}, None)
        await proxy.client.aclose()
    asyncio.run(run())


def test_catalog_is_frozen_and_reused_without_repeated_upstream_requests(tmp_path):
    async def run():
        proxy = FixtureProxy("https://example.invalid", "fake", tmp_path, "2026-10-08")
        calls = []
        async def rpc(method, params):
            calls.append(method)
            return {"result": {"tools": [{"name": "get_faq_conditions"}, {"name": "cancel_booking"}]}}
        proxy.rpc = rpc
        assert await proxy.tools() == {"tools": [{"name": "get_faq_conditions"}]}
        await proxy.tools()
        proxy.catalog = None
        await proxy.tools()
        assert calls == ["tools/list"]
        await proxy.client.aclose()
    asyncio.run(run())


def test_tool_rpc_error_preserves_upstream_contract_without_invalidating_other_cases(tmp_path):
    import httpx
    from starlette.applications import Starlette
    from starlette.routing import Route

    async def run():
        proxy = FixtureProxy("https://example.invalid", "fake", tmp_path, "2026-10-08")
        error = {"code": -32602, "message": "hotelIds must contain at least two identifiers"}
        async def rpc(method, params):
            return {"error": error}
        proxy.rpc = rpc
        app = Starlette(routes=[Route("/mcp", proxy.handle, methods=["POST"])])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://localhost") as client:
            response = await client.post("/mcp", json={"id": 42, "method": "tools/call",
                "params": {"name": "compare_hotels", "arguments": {"hotelIds": []}}})
        assert response.json() == {"jsonrpc": "2.0", "id": 42, "error": error}
        assert proxy.error_count == 0
        assert proxy.tool_rejections == 1
        await proxy.client.aclose()
    asyncio.run(run())
