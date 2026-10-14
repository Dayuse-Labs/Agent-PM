"""Offline tests for evals/langfuse_experiment.py (QA14707 Q01, decision DQ4):
the multi-turn replay on one session, and the trace facts scoped to the last
turn. No network: the facade call, the Redis priming and the Langfuse client
are replaced by fakes — only the harness logic is under test."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest

from evals import langfuse_experiment as exp


@pytest.fixture(autouse=True)
def _no_polling_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(exp, "_TRACE_LOOKUP_DELAY_SECONDS", 0)


def _obs(type_: str, name: str, *, input: Any = None, output: Any = None, start: int = 0,
         metadata: dict[str, Any] | None = None, status_message: str | None = None) -> Any:
    return SimpleNamespace(
        type=type_, name=name, input=input, output=output, start_time=start,
        metadata=metadata or {}, status_message=status_message,
    )


class _FakeLangfuse:
    """`traces` maps trace id -> (timestamp, observations)."""

    def __init__(self, traces: dict[str, tuple[int, list[Any]]]) -> None:
        self._traces = traces
        self.async_api = SimpleNamespace(
            sessions=SimpleNamespace(get=self._session), trace=SimpleNamespace(get=self._trace)
        )

    async def _session(self, session_id: str) -> Any:
        return SimpleNamespace(
            traces=[SimpleNamespace(id=tid, timestamp=ts) for tid, (ts, _) in self._traces.items()]
        )

    async def _trace(self, trace_id: str, fields: str | None = None) -> Any:
        return SimpleNamespace(observations=self._traces[trace_id][1])


def _agent_obs(family: str) -> Any:
    return _obs("AGENT", "v3.chat", metadata={"family": family})


# --- the replay ---------------------------------------------------------------
class _Facade:
    """Records every posted turn; answers `reply to <turn>`."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.primed: list[tuple[str, dict[str, Any]]] = []
        self._fail_on = fail_on

    async def call(self, session_id: str, message: str) -> dict[str, Any]:
        self.calls.append((session_id, message))
        if message == self._fail_on:
            return {"_transport_error": "ReadTimeout: slow"}
        return {"message": f"reply to {message}", "hotels": []}

    async def prime(self, session_id: str, profile: dict[str, Any]) -> None:
        self.primed.append((session_id, profile))


def _run_item(monkeypatch: pytest.MonkeyPatch, item: dict[str, Any], facade: _Facade,
              langfuse: Any = None) -> dict[str, Any]:
    monkeypatch.setattr(exp, "_call_facade", facade.call)
    monkeypatch.setattr(exp, "_prime_profile", facade.prime)
    task = exp.make_task(langfuse, "run1")
    return asyncio.run(task(item=item))


def test_every_user_turn_is_posted_in_order_on_one_session(monkeypatch):
    item = {
        "id": "case",
        "input": {
            "messages": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "recorded answer, never replayed"},
                {"role": "user", "content": "second"},
                {"role": "user", "content": "third"},
            ],
            "profile": {"city": "Paris"},
        },
        "expected_output": {},
    }
    facade = _Facade()
    output = _run_item(monkeypatch, item, facade)

    session_id = "obs6-run1-case"
    assert facade.calls == [(session_id, "first"), (session_id, "second"), (session_id, "third")]
    assert facade.primed == [(session_id, {"city": "Paris"})]  # once, before the first turn
    # the graded reply is the one to the LAST turn, the one before it is kept
    assert output["response"]["message"] == "reply to third"
    assert output["previous_reply"] == "reply to second"
    assert output["turns_replayed"] == 3


def test_previous_reply_is_the_real_one_or_else_the_recorded_one(monkeypatch):
    item = {
        "id": "case",
        "input": {
            "messages": [
                {"role": "user", "content": "je cherche un hôtel à paris demain"},
                {"role": "assistant", "content": "Voici 5 hôtels."},
                {"role": "user", "content": "plutôt vers les champs élysées"},
            ]
        },
        "expected_output": {},
    }
    facade = _Facade()
    output = _run_item(monkeypatch, item, facade)
    # two user turns: both are replayed, the REAL reply is the previous one
    assert [m for _, m in facade.calls] == ["je cherche un hôtel à paris demain", "plutôt vers les champs élysées"]
    assert output["previous_reply"] == "reply to je cherche un hôtel à paris demain"

    solo = {
        "id": "solo",
        "input": {"messages": [{"role": "assistant", "content": "Bonjour"}, {"role": "user", "content": "yes"}]},
        "expected_output": {},
    }
    out = _run_item(monkeypatch, solo, _Facade())
    assert out["previous_reply"] == "Bonjour" and out["turns_replayed"] == 1


def test_a_transport_failure_stops_the_replay(monkeypatch):
    item = {
        "id": "case",
        "input": {"messages": [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]},
        "expected_output": {},
    }
    facade = _Facade(fail_on="a")
    output = _run_item(monkeypatch, item, facade)
    assert [m for _, m in facade.calls] == ["a"]  # "b" would answer a question never asked
    assert "_transport_error" in output["response"] and output["turns_replayed"] == 1


def test_an_item_without_user_turn_is_refused():
    with pytest.raises(ValueError):
        exp._user_turns([{"role": "assistant", "content": "hi"}])


# --- the trace facts, scoped to the last turn -----------------------------------
GEOCODE_OK = {"ok": True, "latitude": 48.88, "longitude": 2.35, "country_code": "FR", "profile_delta": {}}
GEOCODE_ASKS = {
    "ok": False,
    "error": "geocode_ambiguous",
    "diagnostics": {"question": "In which city?", "options": []},
}


def _two_turn_item(trace_expectation: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "case",
        "input": {"messages": [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]},
        "expected_output": {"trace": trace_expectation},
    }


def test_trace_facts_are_those_of_the_last_turn(monkeypatch):
    turn1 = [
        _agent_obs("search"),
        _obs("TOOL", "geocode_location", output=json.dumps(GEOCODE_ASKS), status_message="geocode_city_needed"),
        _obs("TOOL", "mcp-generate_booking_link", input={"hotel_id": 1}),
    ]
    turn2 = [
        _agent_obs("search"),
        _obs("TOOL", "geocode_location", output=GEOCODE_OK, start=2),
        _obs("TOOL", "search_offers", input={"lat": 48.88, "date": "2099-01-01"}, start=3),
    ]
    # listed in the "wrong" order on purpose: the timestamp decides, not the position
    langfuse = _FakeLangfuse({"t2": (20, turn2), "t1": (10, turn1)})
    item = _two_turn_item({"geocode_city_needed": False, "tools_not_called": ["generate_booking_link"]})
    trace = _run_item(monkeypatch, item, _Facade(), langfuse)["trace"]

    assert trace["geocode"] == {
        "ok": True, "error": None, "city_needed": False, "options": [], "country_code": "FR",
    }
    assert trace["tool_calls"] == []  # turn 1's mcp-generate_booking_link is not turn 2's
    assert trace["search_offers_args"] == {"lat": 48.88, "date": "2099-01-01"}
    assert trace["family"] == "search"


def test_trace_facts_wait_for_every_turn_trace(monkeypatch):
    """One trace visible after two turns = the last turn's export is in flight:
    the first turn's facts must not stand in for it."""
    turn1 = [_agent_obs("search"), _obs("TOOL", "mcp-generate_booking_link")]
    langfuse = _FakeLangfuse({"t1": (10, turn1)})
    item = _two_turn_item({"tools_not_called": ["generate_booking_link"]})
    trace = _run_item(monkeypatch, item, _Facade(), langfuse)["trace"]
    assert trace["tool_calls"] is None and trace["family"] is None

    # a single-turn item reads the whole session, as it always did
    single = {
        "id": "one",
        "input": {"messages": [{"role": "user", "content": "a"}]},
        "expected_output": {"trace": {"tools_not_called": ["generate_booking_link"]}},
    }
    one = _run_item(monkeypatch, single, _Facade(), langfuse)["trace"]
    assert one["tool_calls"] == ["mcp-generate_booking_link"]


def test_inline_tool_calls_are_keyed_on_the_exact_observation_names():
    facts = exp._facts_from_observations(
        [
            _obs("TOOL", "generate_booking_link"),  # bare name: not the concierge's observation
            _obs("SPAN", "mcp-generate_booking_link"),  # right name, not a TOOL observation
            _obs("TOOL", "mcp-find_hotel_by_name", start=1),
            _obs("TOOL", "mcp-generate_booking_link", start=2),
        ]
    )
    assert facts["tool_calls"] == ["mcp-find_hotel_by_name", "mcp-generate_booking_link"]

    only_wrong = exp._facts_from_observations(
        [_obs("TOOL", "generate_booking_link"), _obs("TOOL", "find_hotel_by_name")]
    )
    assert only_wrong["tool_calls"] == []  # a trace was seen, and no inline call is in it
    assert exp._facts_from_observations([])["tool_calls"] is None  # no trace seen at all


def test_geocode_fact_reads_the_leaf_result():
    asked = exp._facts_from_observations(
        [_obs("TOOL", "geocode_location", output=json.dumps(GEOCODE_ASKS))]
    )["geocode"]
    assert asked["ok"] is False and asked["error"] == "geocode_ambiguous"
    assert asked["city_needed"] is True and asked["options"] == []

    homonym = {
        "ok": False,
        "error": "geocode_ambiguous",
        "diagnostics": {"question": "Which one?", "options": [{"name": "Lyon", "country_code": "FR"}]},
    }
    fact = exp._facts_from_observations([_obs("TOOL", "geocode_location", output=homonym)])["geocode"]
    assert fact["city_needed"] is False and [o["name"] for o in fact["options"]] == ["Lyon"]

    # the status the leaf marks on the span counts too
    by_status = exp._facts_from_observations(
        [_obs("TOOL", "geocode_location", output={"ok": False, "error": "x"}, status_message="geocode_city_needed")]
    )["geocode"]
    assert by_status["city_needed"] is True

    # the LAST call of the turn wins
    last = exp._facts_from_observations(
        [
            _obs("TOOL", "geocode_location", output=GEOCODE_OK, start=2),
            _obs("TOOL", "geocode_location", output=GEOCODE_ASKS, start=1),
        ]
    )["geocode"]
    assert last["ok"] is True

    # no geocode_location observation, or an unreadable output: no fact, never a guess
    assert exp._facts_from_observations([_obs("TOOL", "search_offers", input={})])["geocode"] is None
    assert exp._facts_from_observations([_obs("TOOL", "geocode_location", output="oops")])["geocode"] is None
