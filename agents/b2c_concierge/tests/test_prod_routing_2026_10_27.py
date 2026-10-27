"""Prod 2026-10-26/27, the concierge side of the false dead ends.

C. "I couldn't find that hotel" on messages that named no hotel (« Vasca
   idromassaggio », « 有浴缸 »: triage `details`, `hotel_name` null), on a
   place the triage took for a hotel (« Big Sur »), on a hotel on screen MCP
   knows under another spelling (« double tree » / « DoubleTree by Hilton… »),
   and on « the less expensive ? » with a shortlist on screen, whose details
   lookup failed.
A. the leaf's `unresolved` place question, rendered by template — never the
   "search unavailable" line.

Real spine (`InMemoryRunner`), real `_run_leaf` over a fake A2A leg, fake MCP
session, scripted LLM — triage outputs are the ones Langfuse recorded.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from google.adk.events import Event
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

import b2c_concierge.agent as agent_module
from b2c_concierge import templates
from b2c_concierge.a2a_datapart import encode_datapart, find_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.profile import SessionProfile


def _llm(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class _ScriptedLlm:
    def __init__(self, *plan):
        self.plan = list(plan)
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return _llm(self.plan.pop(0))


class _Leg:
    """The A2A leg: records what it was sent, answers a scripted turn."""

    def __init__(self):
        self.text = "LEAF OUTCOME"
        self.payload: dict | None = None
        self.sent: list[list[genai_types.Part]] = []

    async def run_async(self, ctx):
        self.sent.append(list(ctx.session.events[-1].content.parts or []))
        parts = [genai_types.Part(text=self.text)] if self.text else []
        if self.payload is not None:
            parts.append(encode_datapart(self.payload))
        yield Event(author="hotel_search_leg", invocation_id=ctx.invocation_id,
                    content=genai_types.Content(role="model", parts=parts))

    def query_params(self, turn: int = -1) -> dict:
        data = find_datapart(self.sent[turn]) or {}
        return data.get("query_params") or {}


class _McpResult:
    def __init__(self, data=None, error: str | None = None):
        self.structuredContent = data
        self.isError = error is not None
        self.content = [SimpleNamespace(text=error)] if error else []


@pytest.fixture
def leg(monkeypatch):
    fake = _Leg()
    monkeypatch.setattr(agent_module, "_get_leg", lambda leaf: fake)
    return fake


@pytest.fixture
def mcp(monkeypatch):
    """The concierge's inline MCP session: `script[name]` is a result, an
    exception, or absent (then the test fails on the unexpected call)."""
    script: dict = {}
    calls: list[tuple[str, dict]] = []

    class _Session:
        async def call_tool(self, name, arguments, *, meta=None):
            calls.append((name, dict(arguments)))
            outcome = script[name]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    @asynccontextmanager
    async def _session():
        yield _Session()

    monkeypatch.setattr(agent_module.inline_tools, "_mcp_session", _session)
    return SimpleNamespace(script=script, calls=calls)


def _scripted(monkeypatch, *plan) -> _ScriptedLlm:
    llm = _ScriptedLlm(*plan)
    monkeypatch.setattr(agent_module.litellm, "acompletion", llm)
    return llm


def _triage(**slots) -> str:
    return json.dumps({"family": "search", "language": "en", "pick": "none", **slots})


class _Conversation:
    def __init__(self, store, profile: SessionProfile | None = None):
        self.runner = InMemoryRunner(root_agent)
        self.session = asyncio.run(
            self.runner.session_service.create_session(app_name=self.runner.app_name, user_id="u")
        )
        if profile is not None:
            asyncio.run(store.set(self.session.id, profile))
        self.store = store

    def say(self, message: str) -> tuple[str, list[dict]]:
        async def go():
            content = genai_types.Content(role="user", parts=[genai_types.Part(text=message)])
            return [e async for e in self.runner.run_async(
                user_id="u", session_id=self.session.id, new_message=content)]

        events = asyncio.run(go())
        final = "\n".join(
            p.text for e in events if not e.partial and e.content and e.content.parts
            for p in e.content.parts if p.text
        ).strip()
        markers = []
        for e in events:
            if e.partial and e.content and e.content.parts:
                for p in e.content.parts:
                    if p.text and p.text.startswith(agent_module._US):
                        markers.append(json.loads(p.text[len(agent_module._US):]))
        return final, markers

    def profile(self) -> SessionProfile:
        return asyncio.run(self.store.get(self.session.id))


# --- C1: a details turn that names no hotel is a search ----------------------------


class TestNoHotelNamedIsASearch:
    @pytest.mark.parametrize(("message", "language"), [("有浴缸", "zh"), ("Vasca idromassaggio", "it")])
    def test_an_amenity_message_goes_to_the_search(
        self, monkeypatch, leg, mcp, fake_profile_store, message, language
    ):
        # Langfuse 671ce8ae / 834720a4: triage `details`, `hotel_name` null.
        _scripted(monkeypatch, _triage(family="details", language=language), "Here they are.")
        leg.payload = {"results": [{"hotel_id": 7, "name": "Hotel A"}],
                       "profile_delta": {"city": "Rome"}}
        convo = _Conversation(fake_profile_store, SessionProfile(city="Rome", date_checked=True))

        answer, _ = convo.say(message)

        assert len(leg.sent) == 1, "the search leaf got the turn"
        assert mcp.calls == [], "no name was looked up: none was given"
        for lang in ("en", "it"):
            assert answer != templates.inline_unresolved_response("get_hotel_details", lang)

    def test_a_question_about_the_hotel_on_screen_stays_a_details_turn(
        self, monkeypatch, leg, mcp, fake_profile_store
    ):
        # Negative control: a hotel the shortlist resolves is still looked up.
        _scripted(monkeypatch, _triage(family="details", hotel_name="Hotel Artemide"),
                  "It has a spa.")
        mcp.script["get_hotel_details"] = _McpResult({"hotel": {"hotelId": 7, "name": "Hotel Artemide"},
                                                      "offers": []})
        convo = _Conversation(fake_profile_store, SessionProfile(
            city="Rome", last_results=[{"hotel_id": 7, "name": "Hotel Artemide"}]))

        answer, _ = convo.say("does Hotel Artemide have a spa?")

        assert leg.sent == []
        assert [name for name, _ in mcp.calls] == ["get_hotel_details"]
        assert answer == "It has a spa."


# --- C2: a hotel name nobody has -> the leaf's search, which looks it up as a place ----


class TestANameNoHotelHas:
    def test_big_sur_reaches_the_search_with_its_name(self, monkeypatch, leg, mcp, fake_profile_store):
        # Langfuse d5123bb6: `hotel_name` "Big Sur". Through details, MCP knows
        # no such hotel; the search leaf gets the name (and looks it up as a
        # place: hotel_search_agent.named_hotel._search_the_place).
        _scripted(monkeypatch, _triage(family="details", hotel_name="Big Sur"), "Big Sur hotels.")
        mcp.script["find_hotel_by_name"] = _McpResult(
            {"error": {"kind": "HotelNotFoundError", "query": "Big Sur"}},
            error='No hotel found for "Big Sur"',
        )
        leg.payload = {"results": [{"hotel_id": 3, "name": "Ventana"}], "profile_delta": {"city": "Big Sur"}}
        convo = _Conversation(fake_profile_store, SessionProfile(date_checked=True))

        answer, _ = convo.say("Big Sur")

        assert leg.query_params()["hotel_name"] == "Big Sur"
        assert answer != templates.inline_unresolved_response("get_hotel_details", "en")

    def test_double_tree_is_the_doubletree_on_screen(self, monkeypatch, leg, mcp, fake_profile_store):
        # Langfuse e79a8eb9: « double tree is good but none of these are really
        # private » with the DoubleTree card on screen; MCP has no « Double Tree ».
        _scripted(monkeypatch, _triage(family="details", hotel_name="Double Tree"),
                  "The DoubleTree's pool is shared with other guests.")
        mcp.script["find_hotel_by_name"] = _McpResult(
            {"error": {"kind": "HotelNotFoundError", "query": "Double Tree"}}, error="not found")
        mcp.script["get_hotel_details"] = _McpResult(
            {"hotel": {"hotelId": 42, "name": "DoubleTree by Hilton Sharjah Waterfront Hotel & Residences"},
             "offers": []})
        convo = _Conversation(fake_profile_store, SessionProfile(city="Sharjah", last_results=[
            {"hotel_id": 41, "name": "Sharjah Palace Hotel"},
            {"hotel_id": 42, "name": "DoubleTree by Hilton Sharjah Waterfront Hotel & Residences"},
        ]))

        answer, _ = convo.say("double tree is good but none of these are really private")

        assert ("get_hotel_details", {"hotelId": 42}) in mcp.calls
        assert answer == "The DoubleTree's pool is shared with other guests."
        assert leg.sent == []


# --- C3: « the less expensive » with a shortlist on screen ------------------------------


class TestTheCheapestOnScreen:
    SHOWN = [
        {"hotel_id": 1, "name": "Hampton Inn NY-JFK", "price": "$120.00", "price_eur_cents": 10300,
         "offer_id": "o1", "offer_date": "2026-10-28", "url": "https://www.dayuse.com/hotels/usa/hampton"},
        {"hotel_id": 2, "name": "Hilton Garden Inn Queens / JFK", "price": "$99.00",
         "price_eur_cents": 8500, "offer_id": "o2", "offer_date": "2026-10-28",
         "url": "https://www.dayuse.com/hotels/usa/hgi"},
    ]

    def test_details_failing_still_answers_with_the_card(self, monkeypatch, leg, mcp, fake_profile_store):
        # Langfuse d3889d22: pick=cheapest, a shortlist on screen; the details
        # call failed and the answer was "I couldn't find that hotel".
        _scripted(monkeypatch,
                  _triage(pick="cheapest", price_comparison={"value": "lower", "evidence": "x"}),
                  "The least expensive is the Hilton Garden Inn Queens / JFK.")
        mcp.script["get_hotel_details"] = ConnectionError("MCP down")
        convo = _Conversation(fake_profile_store, SessionProfile(
            city="New York", date="2026-10-28", last_results=[dict(h) for h in self.SHOWN]))

        answer, markers = convo.say("the less expensive ?")

        assert answer == "The least expensive is the Hilton Garden Inn Queens / JFK."
        hotels = [m for m in markers if m["event"] == "hotels"]
        assert hotels and [h["name"] for h in hotels[0]["hotels"]] == ["Hilton Garden Inn Queens / JFK"]
        assert leg.sent == []


# --- A: the leaf's `unresolved` question --------------------------------------------------


class TestTheUnresolvedPlaceQuestion:
    CLARIFICATION = {"schema_version": "1", "kind": "unresolved", "subject": "Galveston", "options": []}

    def test_it_is_asked_by_template_never_as_an_outage(self, monkeypatch, leg, fake_profile_store):
        # What the leaf sends since the fix (it used to send `guards_fired`
        # alone, which the concierge read as an empty, failed leaf turn).
        _scripted(monkeypatch, _triage(day_stated=True))
        leg.text = 'I couldn\'t place "Galveston". Could you tell me the city or the country?'
        leg.payload = {"requires_clarification": True, "clarification": self.CLARIFICATION,
                       "guards_fired": ["geocode_echo_back"]}
        convo = _Conversation(fake_profile_store, SessionProfile(date_checked=True))

        answer, _ = convo.say("Galveston")

        assert answer == 'I couldn\'t place "Galveston". Could you tell me the city or the country?'
        assert "can't reach" not in answer
        assert convo.profile().pending_clarification["clarification"]["kind"] == "unresolved"

    def test_asked_again_it_is_reworded_then_dropped(self, monkeypatch, leg, fake_profile_store):
        _scripted(monkeypatch, _triage(), _triage(answers_pending="yes"), _triage(answers_pending="yes"))
        leg.payload = {"requires_clarification": True, "clarification": self.CLARIFICATION}
        convo = _Conversation(fake_profile_store, SessionProfile(date_checked=True))

        first, _ = convo.say("Galveston")
        second, _ = convo.say("Galveston")
        third, _ = convo.say("Galveston")

        assert first != second
        assert "Galveston" in second
        assert third == templates.clarification_response(
            agent_module.Clarification.model_validate(self.CLARIFICATION), "en",
            templates.CLARIFICATION_MAX_ASKS + 1,
        )

    def test_a_leaf_turn_with_nothing_at_all_is_still_the_outage_line(
        self, monkeypatch, leg, fake_profile_store
    ):
        # Negative control: a leaf that returned nothing (no text, no data) is
        # a failure, and says so.
        _scripted(monkeypatch, _triage())
        leg.text = ""
        leg.payload = None
        convo = _Conversation(fake_profile_store, SessionProfile(date_checked=True, city="Paris"))

        answer, _ = convo.say("Galveston")

        assert answer == templates.leaf_degraded_response("search", "en", "Paris")
