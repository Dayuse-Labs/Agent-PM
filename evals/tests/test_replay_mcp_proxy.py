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
