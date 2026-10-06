import asyncio
import json

import httpx
import pytest

from evals.production_replay import compile_cases, context_for, replay, request_turn, run_case


def row(i, sid, message, **kwargs):
    return {"id": i, "session_id": sid, "created_at": f"2026-03-01T12:00:{i:02d}",
            "user_message": message, **kwargs}


def test_all_turns_preserved_with_duplicates_in_same_split_and_faq_not_excluded():
    cases, stats = compile_cases([row(2, "real1", "Annule ma réservation"), row(1, "real1", "Bonjour"),
                                 row(3, "real2", "bonjour"), row(4, "real2", "Annule ma réservation"),
                                 row(5, "qa-probe", "Bonjour"), row(6, "empty", "")])
    real = [c for c in cases if c["traffic"] == "unclassified"]
    assert real[0]["split"] == real[1]["split"]
    assert all(c["family_hint"] == "faq_or_booking" for c in real)
    assert stats["eligible_turns"] == 5
    assert stats["excluded"] == [{"row_id": 6, "reason": "empty_user_message"}]


def test_no_model_output_or_inferred_market_becomes_browser_input():
    context, missing = context_for({"active_filters": {"client_timezone": "Europe/Paris"},
        "detected_market": {"currency": "USD", "locale": "en-US", "domain": "dayuse.com",
                            "_diag": {"url_locale": "fr-FR", "url_currency": "EUR"}}})
    assert context == {"locale": "fr-FR", "currency": "EUR"}
    assert "client_timezone" in missing


def test_sse_progress_and_token_are_distinct_and_missing_done_fails():
    async def run():
        data = 'event: progress\ndata: {}\n\nevent: token\ndata: {"text":"Hello"}\n\nevent: done\ndata: {"message":"Hello"}\n\n'
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=data))) as client:
            result = await request_turn(client, "http://localhost/chat", {}, {})
            assert set(result["timing_ms"]) == {"progress", "token", "done", "total"}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text='event: progress\ndata: {}\n\n'))) as client:
            with pytest.raises(ValueError, match="final"):
                await request_turn(client, "http://localhost/chat", {}, {})
    asyncio.run(run())


def test_resume_restarts_partial_conversation_and_never_skips_context(tmp_path, monkeypatch):
    seen = []
    async def request(client, endpoint, body, headers):
        seen.append((body["session_id"], body["message"]))
        if len(seen) == 2:
            raise httpx.ReadTimeout("simulated")
        return {"response": {"message": "ok"}, "timing_ms": {"total": 1}}
    monkeypatch.setattr("evals.production_replay.request_turn", request)
    cases, _ = compile_cases([row(1, "real", "Lyon demain"), row(2, "real", "avec piscine")])
    async def run():
        first = await run_case(cases[0], tmp_path, "http://localhost", "v", "r", 1)
        assert not first["complete"]
        second = await run_case(cases[0], tmp_path, "http://localhost", "v", "r", 1)
        assert second["complete"]
        assert seen[0][0] != seen[2][0]
        assert [s[1] for s in seen] == ["Lyon demain", "avec piscine"] * 2
        await run_case(cases[0], tmp_path, "http://localhost", "v", "r", 1)
        assert len(seen) == 4
    asyncio.run(run())


def test_remote_endpoint_and_changed_resume_provenance_rejected(tmp_path):
    async def run():
        with pytest.raises(ValueError, match="local"):
            await replay([], tmp_path, "https://production.example/chat", "v", 1, {})
        await replay([], tmp_path, "http://localhost/chat", "v", 1, {"sha": "first"})
        with pytest.raises(ValueError, match="configuration"):
            await replay([], tmp_path, "http://localhost/chat", "v", 1, {"sha": "changed"})
        assert json.loads((tmp_path / "manifest.json").read_text())["complete"]
    asyncio.run(run())


def test_invalidated_run_cannot_reuse_completed_cases(tmp_path):
    (tmp_path / "INVALIDATED.json").write_text('{"reason":"provider errors"}')
    with pytest.raises(ValueError, match="invalidated"):
        asyncio.run(replay([], tmp_path, "http://localhost/chat", "v", 1, {}))
