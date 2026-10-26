"""QA 2026-10-20: the date question and its day chips reach the payload the
widget reads, on both transports — over the real composed ASGI app (offline,
triage and leaf stubbed at the spine's boundaries)."""
from __future__ import annotations

import json

import pytest

import b2c_concierge.agent as agent_module
from b2c_concierge import templates
from b2c_concierge.triage import Triage

pytestmark = pytest.mark.date_unsettled


@pytest.fixture
def dateless_search(monkeypatch):
    async def fake_classify(message, budget, invocation_id="", *, recent_messages=None, previous_question=None):
        budget.charge("triage")
        return Triage("search", "fr", used_llm=False)

    async def no_leaf(*args, **kwargs):
        raise AssertionError("the leaf must not run before the day is known")

    monkeypatch.setattr(agent_module, "classify", fake_classify)
    monkeypatch.setattr(agent_module, "_run_leaf", no_leaf)


def test_the_json_turn_asks_the_day_with_its_chips(client, dateless_search):
    r = client.post("/v3/chat", json={"message": "un hôtel avec piscine à Nice", "locale": "fr"})

    assert r.status_code == 200
    body = r.json()
    assert body["message"] == templates.date_question("fr")
    assert body["suggestions"] == templates.date_chips("fr")
    assert body["hotels"] is None


def test_the_streamed_turn_ends_on_the_same_question_and_chips(client, dateless_search):
    r = client.post("/v3/chat/stream", json={"message": "un hôtel avec piscine à Nice", "locale": "fr"})

    assert r.status_code == 200
    done = [
        json.loads(block.split("data:", 1)[1])
        for block in r.text.strip().split("\n\n")
        if block.startswith("event: done")
    ]
    assert len(done) == 1
    assert done[0]["message"] == templates.date_question("fr")
    assert done[0]["suggestions"] == templates.date_chips("fr")
