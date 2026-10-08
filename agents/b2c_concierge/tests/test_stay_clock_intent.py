"""Preserve midnight and a duration across clarification, without prose regexes."""

import asyncio
import json
from types import SimpleNamespace

import pytest


from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from b2c_concierge.agent import root_agent
from b2c_concierge.a2a_datapart import encode_datapart, find_datapart
from b2c_concierge.profile import SessionProfile, apply_profile_delta, leaf_profile_view
from b2c_concierge.triage import _grounded_window
from hotel_search_agent.datetime_resolver import resolve_search_timeslot
from hotel_search_agent.response_bridge import STATE_EXACT_WINDOW_KEY, _hhmm_from_total, normalize_hotel

from .test_spine_profile import fake_leg, _new_session, _run_turn, _scripted_llm  # noqa: F401


def _ctx_with_profile(profile, message):
    return SimpleNamespace(
        state={},
        user_content=genai_types.Content(
            role="user",
            parts=[
                genai_types.Part(text=message),
                encode_datapart({"profile_in": profile}),
            ],
        ),
    )


def _Tool(name):
    return SimpleNamespace(name=name)


@pytest.mark.parametrize("end", ["00:00", "24:00"])
def test_semantic_end_of_day_keeps_midnight(end):
    message = "Orario 21 fino a mezzanotte"
    assert _grounded_window(
        {
            "requested_window": {
                "start": "21:00",
                "end": end,
                "end_boundary": "end_of_day",
                "evidence": message,
            }
        },
        message,
    ) == ("21:00", "24:00")


@pytest.mark.parametrize(
    "raw,message,expected",
    [
        ({"start": "00:00", "end": "20:00"}, "en journée jusqu’au soir 20h", (None, "20:00")),
        ({"start": "14:30", "end": "23:00"}, "à partir de 14:30", ("14:30", None)),
        ({"start": "21:00", "end": "24:00"}, "21 fino a mezzanotte", ("21:00", "24:00")),
        ({"end": "24:00"}, "hasta medianoche", (None, "24:00")),
        ({"start": "00:00", "end": "20:00"}, "en journée", None),
    ],
)
def test_keep_supported_endpoint_without_invented_other_bound(raw, message, expected):
    assert _grounded_window({"requested_window": {**raw, "evidence": message}}, message) == expected


def test_midnight_canonical_value_cannot_copy_prior_turn_evidence():
    assert _grounded_window(
        {"requested_window": {"end": "24:00", "evidence": "hasta medianoche"}},
        "otras opciones",
    ) is None


@pytest.mark.parametrize("message,start,end,expected", [
    ("1300 - 1800", "13:00", "18:00", ("13:00", "18:00")),
    ("0930–1745", "09:30", "17:45", ("09:30", "17:45")),
    ("1300 - 1800", "13:30", "18:00", (None, "18:00")),
    ("1300 - 1800", "01:00", "18:00", (None, "18:00")),
    ("13001800", "13:00", "18:00", None),
    ("AB1300 CD1800", "13:00", "18:00", None),
])
def test_compact_clock_witness_requires_exact_complete_numeric_token(message, start, end, expected):
    # The model owns intent; code only validates its claimed clock against the
    # actual quoted numbers. Never split IDs or reinterpret 24h as 12h.
    assert _grounded_window({"requested_window": {
        "start": start, "end": end, "evidence": message,
    }}, message) == expected


@pytest.mark.parametrize(
    "raw,message",
    [
        (
            {"start": "21:00", "end": "22:00", "end_boundary": "end_of_day", "evidence": "21 to 22"},
            "21 to 22",
        ),
        (
            {"start": "21:00", "end": "00:00", "end_boundary": "end_of_day", "evidence": "old turn"},
            "other options",
        ),
        ({"start": "24:00", "end": "24:00", "evidence": "24:00–24:00"}, "24:00–24:00"),
        ({"start": "21:00", "end": "24:30", "evidence": "21:00–24:30"}, "21:00–24:30"),
    ],
)
def test_boundary_label_cannot_override_another_clock_or_missing_evidence(raw, message):
    assert _grounded_window({"requested_window": raw}, message) is None


def test_midnight_adapter_uses_valid_mcp_superset_but_keeps_exact_bound():
    ctx = _ctx_with_profile({"requested_window": {"start": "21:00", "end": "24:00"}}, "Altre opzioni")
    args = {"timeSlot": {"startHour": 21, "endHour": 23}}
    resolve_search_timeslot(_Tool("search_offers"), args, ctx)
    assert args["timeSlot"] == {"startHour": 21, "endHour": 23}  # maximum MCP schema accepts
    assert ctx.state[STATE_EXACT_WINDOW_KEY] == {"start_total": 1260, "end_total": 1440}
    assert _hhmm_from_total(1440) == "24:00"
    hotel = {
        "hotelId": 1,
        "offers": [
            {"ratePlanUuid": "too-early", "priceEuro": 5000, "startHour": 17, "endHour": 23},
            {"ratePlanUuid": "midnight", "priceEuro": 8000, "startHour": 17, "endHour": 0},
        ],
    }
    assert normalize_hotel(hotel, (1260, 1440))["offer_id"] == "midnight"


def test_duration_survives_city_then_arrival_and_leaf_cannot_overwrite(
    monkeypatch, fake_leg, fake_profile_store  # noqa: F811
):  # noqa: F811
    fake_leg.response_payload = {"results": [], "profile_delta": {}}
    _scripted_llm(
        monkeypatch,
        json.dumps(
            {
                "family": "search",
                "language": "de",
                "requested_window": {"duration_minutes": 120, "evidence": "nur zwei Stunden"},
            }
        ),
        "Welche Stadt?",
        '{"family":"search","language":"de"}',
        "Wann möchten Sie ankommen?",
        json.dumps(
            {
                "family": "search",
                "language": "de",
                "requested_window": {"start": "14:30", "evidence": "14:30"},
            }
        ),
        "Hier sind die Angebote.",
    )
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    _run_turn(runner, session.id, "nur zwei Stunden")
    outgoing = find_datapart(fake_leg.seen_outgoing_parts)["profile_in"]
    assert outgoing.get("requested_duration_minutes") == 120
    assert outgoing["timeslot_start"] is None and outgoing["timeslot_end"] is None
    fake_leg.response_payload = {"results": [], "profile_delta": {"city": "Hannover"}}
    _run_turn(runner, session.id, "Hannover")
    profile = asyncio.run(fake_profile_store.get(session.id))
    assert profile.to_dict().get("requested_duration_minutes") == 120
    _run_turn(runner, session.id, "14:30")
    outgoing = find_datapart(fake_leg.seen_outgoing_parts)["profile_in"]
    assert (outgoing["timeslot_start"], outgoing["timeslot_end"]) == ("14:30", "16:30")
    profile = asyncio.run(fake_profile_store.get(session.id))
    apply_profile_delta(profile, {"requested_duration_minutes": {"op": "clear"}}, "other options")
    assert leaf_profile_view(SessionProfile.from_dict(profile.to_dict()))["requested_duration_minutes"] == 120


def test_owned_duration_without_arrival_blocks_invented_leaf_clock():
    ctx = _ctx_with_profile({"requested_duration_minutes": 120, "requested_window": {}}, "Hannover")
    args = {"duration": "PT2H", "timeSlot": {"startHour": 0, "endHour": 2}}
    resolve_search_timeslot(_Tool("search_offers"), args, ctx)
    assert "timeSlot" not in args and "duration" not in args
    assert STATE_EXACT_WINDOW_KEY not in ctx.state


@pytest.mark.parametrize(
    "update,expected_duration,expected_window",
    [
        ({"clear": True, "evidence": "any time"}, None, (None, None)),
        ({"replace": True, "evidence": "in the evening instead"}, None, (None, None)),
        ({"start": "15:00", "end": "19:00", "evidence": "15:00 to 19:00"}, None, ("15:00", "19:00")),
        ({"start": "22:00", "evidence": "22:00"}, 120, ("22:00", "24:00")),
    ],
)
def test_new_timing_updates_duration_without_leaking_old_bounds(
    monkeypatch,
    fake_leg,  # noqa: F811
    fake_profile_store,
    update,
    expected_duration,
    expected_window,
):
    fake_leg.response_payload = {"results": [], "profile_delta": {}}
    _scripted_llm(
        monkeypatch,
        json.dumps(
            {
                "family": "search",
                "language": "en",
                "requested_window": update,
            }
        ),
        "Updated.",
    )
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    raw = SessionProfile(city="Hannover", requested_window={"start": "14:30", "end": "16:30"}).to_dict()
    raw["requested_duration_minutes"] = 120
    profile = SessionProfile.from_dict(raw)
    profile.restore_requested_window()
    asyncio.run(fake_profile_store.set(session.id, profile))
    _run_turn(runner, session.id, update["evidence"])
    outgoing = find_datapart(fake_leg.seen_outgoing_parts)["profile_in"]
    assert outgoing["requested_duration_minutes"] == expected_duration
    assert (outgoing["timeslot_start"], outgoing["timeslot_end"]) == expected_window


def test_departure_only_midnight_does_not_exclude_late_starts_or_invent_arrival():
    from hotel_search_agent.response_bridge import capture_after_tool

    ctx = _ctx_with_profile({'requested_window': {'start': None, 'end': '24:00'}}, 'until midnight')
    args = {'timeSlot': {'endHour': 23}}
    resolve_search_timeslot(_Tool('search_offers'), args, ctx)
    assert args['timeSlot'] == {'startHour': 23, 'endHour': 23}
    assert ctx.state[STATE_EXACT_WINDOW_KEY] == {'start_total': None, 'end_total': 1440}
    capture_after_tool(_Tool('search_offers'), args, ctx,
                       {'structuredContent': {'results': [], 'total': 0}})
    captured = ctx.state['temp:hotel_search_budget_timeslot']
    assert captured['timeslot_end'] == '24:00'
    assert 'timeslot_start' not in captured


def test_unsupported_full_day_placeholder_cannot_overwrite_saved_departure():
    from b2c_concierge.triage import _grounded_window
    assert _grounded_window({'requested_window': {
        'start': '00:00', 'end': '24:00', 'evidence': 'en journée',
    }}, 'Chambre en journée près de moi') is None
    assert _grounded_window({'requested_window': {
        'start': '00:00', 'end': '24:00', 'evidence': '00:00–24:00',
    }}, '00:00–24:00') == ('00:00', '24:00')
