import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from evals.replay_runtime import ClockMiddleware, ReplayDate, ReplayDatetime, replay_headers


def test_clock_is_per_request_and_preserves_client_timezone():
    async def run():
        results = []

        async def app(scope, receive, send):
            await asyncio.sleep(0.01)
            results.append((ReplayDate.today().isoformat(), ReplayDatetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()))

        wrapped = ClockMiddleware(app)

        async def invoke(value):
            await wrapped({"type": "http", "headers": [(b"x-replay-clock", value.encode()),
                (b"x-replay-source-today", value[:10].encode())]}, None, None)

        await asyncio.gather(invoke("2026-03-02T01:00:00Z"), invoke("2026-07-04T01:00:00Z"))
        assert sorted(results) == [("2026-03-02", "2026-03-01"), ("2026-07-04", "2026-07-03")]
        assert replay_headers.get() == {}

    asyncio.run(run())


def test_real_clock_is_unchanged_without_replay_context():
    assert abs((ReplayDatetime.now(UTC) - datetime.now(UTC)).total_seconds()) < 1


def test_mcp_calls_carry_their_own_context_not_the_transport_creation_context(monkeypatch):
    import httpx
    from mcp import ClientSession
    from evals.replay_runtime import install_propagation

    captured = []

    async def fake(self, name, arguments, *args, meta=None, **kwargs):
        await asyncio.sleep(0)
        captured.append(meta)

    monkeypatch.setattr(ClientSession, "call_tool", fake)
    # Register both originals with monkeypatch before the installer wraps them.
    monkeypatch.setattr(httpx.AsyncClient, "send", httpx.AsyncClient.send)
    install_propagation()

    async def invoke(day):
        token = replay_headers.set({"x-replay-source-today": day})
        try:
            await ClientSession.call_tool(None, "search_offers", {}, meta={"original": True})
        finally:
            replay_headers.reset(token)

    async def run():
        await asyncio.gather(invoke("2026-07-01"), invoke("2026-09-01"))

    asyncio.run(run())
    assert {m["dayuse_replay"]["x-replay-source-today"] for m in captured} == {"2026-07-01", "2026-09-01"}
    assert all(m["original"] for m in captured)
