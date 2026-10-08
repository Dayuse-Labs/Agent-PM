"""Grounded landmark intent traverses the concierge and real leaf callback."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types

import b2c_concierge.agent as agent_module
from b2c_common.confirmed_location import grounded_landmark
from b2c_concierge.profile import SessionProfile
from hotel_search_agent.geocode_tool import inject_profile_geo_context

from .test_spine import _drive_in, _new_session, scripted  # noqa: F401

MESSAGE = "Nahe Flughafen Wien Schwechat"
INTENT = {"query": "Flughafen Wien Schwechat", "city": "Wien", "country_guess": "AT",
          "evidence": "Flughafen Wien Schwechat"}


@pytest.mark.parametrize("patch", [{"query": "Paris airport"}, {"evidence": "old message"},
                                    {"city": "Paris"}, {"country_guess": "Austria"},
                                    {"query": ""}, {"city": 3}])
def test_landmark_must_be_grounded_in_current_request(patch):
    assert grounded_landmark({**INTENT, **patch}, MESSAGE) is None


def test_landmark_does_not_require_inventing_a_parent_city():
    assert grounded_landmark({"query": "JFK", "evidence": "JFK"}, "Near JFK") == {
        "query": "JFK", "city": None, "country_guess": None}


def test_airport_intent_overrides_wrong_municipality_and_leaf_device_call(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Paris", country_anchor="FR",
        search_anchor={"type": "gps", "lat": 48.15, "lon": 16.47},
        date="2026-11-01", budget_max=90, timeslot_start="13:00", timeslot_end="18:00")))
    seen = []

    async def leaf(leaf, ctx, profile_in, **kwargs):
        payload = {"profile_in": profile_in, "query_params": kwargs["query_params"]}
        part = convert_a2a_part_to_genai_part(a2a_types.Part(root=a2a_types.DataPart(data=payload)))
        tool_ctx = SimpleNamespace(state={}, user_content=types.Content(role="user", parts=[types.Part(text=MESSAGE), part]))
        args = {"city": "Schwechat", "origin": "device", "country_code": "FR",
                "areas": [{"query": "Schwechat", "kind": "municipality", "country": "AT", "evidence": "Schwechat"}]}
        response = inject_profile_geo_context(SimpleNamespace(name="geocode_location"), args, tool_ctx)
        seen.append((profile_in, kwargs, args, response))
        return "No offers", {"results": []}

    scripted(json.dumps({"family": "search", "language": "de", "requested_landmark": INTENT,
        "requested_areas": [{"query": "Schwechat", "kind": "municipality", "country": "AT", "evidence": "Schwechat"}]}), "Keine Angebote.")
    monkeypatch.setattr(agent_module, "_run_leaf", leaf)
    _drive_in(runner, session.id, MESSAGE)
    profile, kwargs, args, response = seen[0]
    assert response is None  # normal provider resolution next, not a city or GPS short-circuit
    assert profile["city"] == "Wien" and profile["zone"] == INTENT["query"]
    assert profile["search_areas"] is None and profile["country_anchor"] is None
    assert profile["date"] == "2026-11-01" and profile["budget_max"] == 90
    assert (profile["timeslot_start"], profile["timeslot_end"]) == ("13:00", "18:00")
    assert args["city"] == "Wien" and args["zone"] == INTENT["query"]
    assert args["origin"] == "destination" and args["country_guess"] == "AT"
    assert profile["search_anchor"] == {"type": "gps", "lat": 48.15, "lon": 16.47}
    assert args["proximity_lat"] == 48.15 and args["proximity_lon"] == 16.47
    assert not args.get("areas") and not args.get("country_code")
    assert kwargs["query_params"]["landmark_authoritative"] is True
