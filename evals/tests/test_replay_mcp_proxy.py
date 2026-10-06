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
