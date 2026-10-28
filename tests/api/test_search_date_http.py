"""2026-10-28: the place-and-day question, the day said after a search, their
day chips reach the payload the widget reads,
on both transports — over the real composed ASGI app (offline, triage and leaf
stubbed at the spine's boundaries). Replaces the isolated day question of
2026-10-20, whose turn ran before the leaf."""
from __future__ import annotations

import json

import pytest

import b2c_concierge.agent as agent_module
from b2c_concierge import templates
from b2c_concierge.date_format import format_date_human
from b2c_concierge.requested_date import reference_today
from b2c_concierge.triage import Triage

pytestmark = pytest.mark.date_unsettled


def _stub(monkeypatch, response):
    calls = []

    async def fake_classify(message, budget, invocation_id="", *, recent_messages=None, previous_question=None):
        budget.charge("triage")
        return Triage("search", "fr", used_llm=False)

    async def fake_leaf(leaf, ctx, profile_in, **kwargs):
        calls.append(profile_in)
        return "", dict(response)

    async def fake_synthesis(self, **kwargs):
        return "Voici des hôtels."

    monkeypatch.setattr(agent_module, "classify", fake_classify)
    monkeypatch.setattr(agent_module, "_run_leaf", fake_leaf)
    monkeypatch.setattr(agent_module._B2cConcierge, "_synthesize_with_guards", fake_synthesis)
    return calls


def _done(text: str) -> dict:
    (done,) = [
        json.loads(block.split("data:", 1)[1])
        for block in text.strip().split("\n\n")
        if block.startswith("event: done")
    ]
    return done


@pytest.fixture
def no_place(monkeypatch):
    return _stub(monkeypatch, {"destination_missing": True})


def test_the_json_turn_asks_the_place_and_the_day_with_the_chips(client, no_place):
    r = client.post("/v3/chat", json={"message": "un hôtel avec piscine", "locale": "fr"})

    assert r.status_code == 200
    body = r.json()
    assert body["message"] == templates.place_question("fr", ask_day=True)
    assert body["suggestions"] == templates.date_chips("fr")
    assert body["hotels"] is None
    assert len(no_place) == 1  # the leaf ran: the question is not asked before it


def test_the_streamed_turn_ends_on_the_same_question_and_chips(client, no_place):
    r = client.post("/v3/chat/stream", json={"message": "un hôtel avec piscine", "locale": "fr"})

    assert r.status_code == 200
    done = _done(r.text)
    assert done["message"] == templates.place_question("fr", ask_day=True)
    assert done["suggestions"] == templates.date_chips("fr")


def test_a_search_with_no_day_says_the_day_and_offers_the_next_ones(client, monkeypatch):
    today = reference_today(None).isoformat()
    _stub(monkeypatch, {
        "results": [{"hotel_id": 1, "name": "Hôtel A"}],
        "profile_delta": {"city": "Nice"},
        "search_date": {"date": today, "same_day": True},
    })

    r = client.post("/v3/chat/stream", json={"message": "un hôtel avec piscine à Nice", "locale": "fr"})

    done = _done(r.text)
    notice = templates.date_retained_notice(format_date_human(today, "fr"), "fr", with_chips=True)
    assert done["message"] == f"Voici des hôtels.\n\n{notice}"
    assert done["suggestions"] == ["Demain", "Après-demain"]
