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
    _place_check(monkeypatch, names_a_place=True)  # « à Nice »


def _place_check(monkeypatch, *, names_a_place: bool) -> None:
    """The turn's second LLM call (`place_check`), stubbed: tests stay offline."""
    async def fake_names_a_place(request, budget, invocation_id=""):
        budget.charge("place_check")
        return names_a_place

    monkeypatch.setattr(agent_module, "names_a_place", fake_names_a_place)


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


@pytest.mark.parametrize("path", ["/v3/chat", "/v3/chat/stream"])
def test_a_request_naming_no_place_asks_the_day_and_the_place_without_chips(
    client, dateless_search, monkeypatch, path
):
    _place_check(monkeypatch, names_a_place=False)

    r = client.post(path, json={"message": "une chambre avec jacuzzi", "locale": "fr"})

    assert r.status_code == 200
    if path == "/v3/chat":
        body = r.json()
    else:
        (body,) = [
            json.loads(block.split("data:", 1)[1])
            for block in r.text.strip().split("\n\n")
            if block.startswith("event: done")
        ]
    assert body["message"] == templates.date_place_question("fr")
    assert body["suggestions"] == []
    assert body["turn_facts"]["clarification_reason"] == "location"
