"""QA14707 (Q16): the market's country travels from the request to the leaf.

The widget sends `entry_market_country` (its `marketContext.country_code`) in
every request body, next to `locale`, which on the en/USD market is a bare
"en". The facade validates it (ISO 3166-1 alpha-2), stores it in the
concierge-owned profile field `entry_market_country`, and the leaf receives it
in `profile_in` for DQ8's market tie-break. It is not the response's
`entry_market_country`, which `_infer_market_country` derives from results.
"""
from __future__ import annotations

import asyncio

import pytest
from google.adk.runners import InMemoryRunner

import b2c_concierge.facade as facade
from b2c_concierge.a2a_datapart import find_datapart
from b2c_concierge.agent import root_agent
from b2c_concierge.facade import _native_context_delta, _parse_market_country
from b2c_concierge.profile import SessionProfile, apply_profile_delta, leaf_profile_view

from .test_spine_profile import _new_session, _run_turn, _scripted_llm, fake_leg  # noqa: F401

_INVALID = ["USA", "", "  ", "U1", "É1", 12, None, ["US"], {"code": "US"}]


@pytest.fixture
def store(monkeypatch, fake_profile_store):
    monkeypatch.setattr(facade, "get_profile_store", lambda: fake_profile_store)
    return fake_profile_store


def _intake(session_id: str, body: dict) -> SessionProfile:
    asyncio.run(facade._apply_native_context(session_id, body, 1))
    return asyncio.run(facade.get_profile_store().get(session_id))


class TestTheFacadeIntake:
    def test_a_valid_code_is_uppercased(self):
        assert _parse_market_country("us") == "US"
        assert _parse_market_country(" FR ") == "FR"
        assert _native_context_delta({"entry_market_country": "us"}, 0) == {
            "entry_market_country": "US"
        }

    @pytest.mark.parametrize("bad", _INVALID)
    def test_anything_else_is_dropped(self, bad):
        assert _parse_market_country(bad) is None
        assert _native_context_delta({"entry_market_country": bad}, 0) == {}

    def test_the_request_market_is_stored_in_the_profile(self, store):
        profile = _intake("s1", {"entry_market_country": "us", "locale": "en", "currency": "USD"})

        assert profile.entry_market_country == "US"
        assert (profile.locale, profile.currency) == ("en", "USD")

    @pytest.mark.parametrize("bad", _INVALID)
    def test_an_invalid_value_carries_the_stored_one_over(self, store, bad):
        _intake("s1", {"entry_market_country": "us"})

        assert _intake("s1", {"entry_market_country": bad}).entry_market_country == "US"
        assert _intake("s1", {"entry_market_country": bad, "locale": "en"}).entry_market_country == "US"

    def test_a_new_market_replaces_the_old_one(self, store):
        _intake("s1", {"entry_market_country": "us"})

        assert _intake("s1", {"entry_market_country": "mx"}).entry_market_country == "MX"

    def test_it_round_trips_through_the_profile_serialization(self):
        profile = SessionProfile(entry_market_country="US")

        assert SessionProfile.from_dict(profile.to_dict()).entry_market_country == "US"
        assert SessionProfile.from_dict({}).entry_market_country is None


class TestConciergeOwned:
    def test_a_leaf_delta_neither_sets_nor_clears_it(self):
        profile = SessionProfile(entry_market_country="US")

        apply_profile_delta(profile, {"entry_market_country": "FR"}, "")
        assert profile.entry_market_country == "US"
        apply_profile_delta(profile, {"entry_market_country": {"op": "set", "value": "FR"}}, "")
        assert profile.entry_market_country == "US"
        apply_profile_delta(profile, {"entry_market_country": {"op": "clear"}}, "")
        assert profile.entry_market_country == "US"

    def test_a_city_change_keeps_it(self):
        # The market is where the request came from, not the destination.
        profile = SessionProfile(city="Paris", country_anchor="FR", entry_market_country="US")

        apply_profile_delta(profile, {"city": "New York"}, "New York")

        assert profile.entry_market_country == "US"

    def test_it_is_in_the_leaf_view(self):
        assert leaf_profile_view(SessionProfile(entry_market_country="US"))["entry_market_country"] == "US"


class TestFromTheRequestToTheLeaf:
    def test_the_leaf_receives_the_market_and_its_delta_cannot_change_it(
        self, monkeypatch, fake_leg, store  # noqa: F811
    ):
        fake_leg.response_payload = {
            "results": [{"hotel_id": 1, "name": "Hotel A"}],
            "profile_delta": {"city": "Valley Stream", "entry_market_country": {"op": "clear"}},
        }
        _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "Here is a hotel.")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)
        _intake(session.id, {"entry_market_country": "us", "locale": "en"})

        _run_turn(runner, session.id, "Allows cats. Near 11580")

        profile_in = find_datapart(fake_leg.seen_outgoing_parts)["profile_in"]
        assert (profile_in["entry_market_country"], profile_in["locale"]) == ("US", "en")
        stored = asyncio.run(store.get(session.id))
        assert stored.city == "Valley Stream"
        assert stored.entry_market_country == "US"

    def test_with_no_market_the_leaf_gets_none(self, monkeypatch, fake_leg, store):  # noqa: F811
        fake_leg.response_payload = {"results": [], "profile_delta": {}}
        _scripted_llm(monkeypatch, '{"family": "search", "language": "en"}', "reply")
        runner = InMemoryRunner(root_agent)
        session = _new_session(runner)

        _run_turn(runner, session.id, "looking for a hotel")

        assert find_datapart(fake_leg.seen_outgoing_parts)["profile_in"]["entry_market_country"] is None
