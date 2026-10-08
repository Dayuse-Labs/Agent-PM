"""Past user windows, distinct from still-bookable offer windows (Melbourne replay)."""
from datetime import UTC, datetime

import pytest

import b2c_concierge.agent as agent_module
import b2c_concierge.window_guard as guard
from b2c_concierge.inline_tools import _normalize_hotel_for_display
from hotel_search_agent.response_bridge import normalize_hotel

from .test_spine import _drive_events, _marker_payloads, scripted  # noqa: F401

NOW = datetime(2026, 10, 8, 5, 10, tzinfo=UTC)  # Melbourne 16:10, LA 22:10 previous day
CARD = {"hotel_id": 1, "name": "Example", "timezone": "Australia/Melbourne",
        "offer_date": "2026-10-08", "timeslots": [{"start": "08:00", "end": "20:00"}]}


@pytest.mark.parametrize(("day", "end", "zone", "expected"), [
    ("2026-10-08", "14:00", "Australia/Melbourne", True),
    ("2026-10-08", "16:10", "Australia/Melbourne", True),
    ("2026-10-08", "16:11", "Australia/Melbourne", False),
    ("2026-10-09", "14:00", "Australia/Melbourne", False),
    ("2026-10-08", "14:00", "America/Los_Angeles", False),
    ("2026-10-08", "24:00", "Australia/Melbourne", False),
    ("2026-10-08", None, "Australia/Melbourne", False),
    ("2026-10-08", "14:00", "Not/AZone", False),
    (None, "14:00", "Australia/Melbourne", False),
])
def test_request_expiry_uses_destination_date_and_clock(day, end, zone, expected):
    assert guard.requested_window_has_ended(
        [{**CARD, "timezone": zone}], day, end, now=NOW
    ) is expected


def test_unknown_and_mixed_destinations_do_not_prove_whole_request_expired():
    check = guard.requested_window_has_ended
    assert not check([], "2026-10-08", "14:00", now=NOW)
    assert not check([CARD, {"hotel_id": 2}], "2026-10-08", "14:00", now=NOW)
    assert not check([CARD, {**CARD, "timezone": "America/Los_Angeles"}],
                     "2026-10-08", "14:00", now=NOW)


@pytest.mark.parametrize(("day", "instant", "expected"), [
    ("2026-10-08", "2026-10-08T18:00:00+00:00", False),
    ("2026-10-08", "2026-10-09T12:59:00+00:00", False),
    ("2026-10-08", "2026-10-09T13:00:00+00:00", True),
    ("2026-10-08", "2026-10-09T14:00:00+00:00", True),
    ("2026-12-31", "2027-01-01T13:59:00+00:00", False),
    ("2026-12-31", "2027-01-01T14:00:00+00:00", True),
])
def test_overnight_request_expires_on_departure_day(day, instant, expected):
    assert guard.requested_window_has_ended(
        [{**CARD, "timezone": "America/Chicago"}], day, "08:00",
        requested_start="23:00", now=datetime.fromisoformat(instant),
    ) is expected


def test_overnight_request_does_not_trigger_past_window_question(scripted, monkeypatch):  # noqa: F811
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 10, 8, 18, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(guard, "datetime", Clock)
    llm, leaves = scripted('{"family":"search","language":"en"}',
                          "These are the closest offers, not an overnight match.", response={
        "results": [{**CARD, "timezone": "America/Chicago"}],
        "search_date": {"date": "2026-10-08"},
        "profile_delta": {"city": "Chicago", "timeslot_start": "23:00", "timeslot_end": "08:00"},
    })
    events = _drive_events("11pm-8am")
    final = " ".join(p.text for e in events if not e.partial for p in e.content.parts if p.text)
    assert "already ended" not in final
    assert "closest offers" in final
    assert len(llm.calls) == 2
    assert len(leaves) == 1


@pytest.mark.parametrize("normalizer", [normalize_hotel, lambda h: _normalize_hotel_for_display(h, None)])
def test_both_mcp_paths_preserve_hotel_timezone(normalizer):
    assert normalizer({"hotelId": 1, "timezone": "Australia/Melbourne"})["timezone"] == "Australia/Melbourne"


def test_expired_request_blocks_cards_and_synthesis(scripted, monkeypatch):  # noqa: F811
    class Clock:
        @staticmethod
        def now(tz):
            return NOW.astimezone(tz)
    monkeypatch.setattr(guard, "datetime", Clock)
    llm, leaves = scripted('{"family":"search","language":"en"}',
                          "These offers fully cover your time slot today.", response={
        "results": [CARD], "search_date": {"date": "2026-10-08"},
        "profile_delta": {"city": "Melbourne", "timeslot_start": "10:00", "timeslot_end": "14:00"},
    })
    events = _drive_events("10am-2pm")
    final = " ".join(p.text for e in events if not e.partial for p in e.content.parts if p.text)
    assert "Which date" in final
    assert "10:00" in final and "14:00" in final
    assert len(llm.calls) == 1  # no synthesis inventing availability
    assert len(leaves) == 1  # no automatic next-day search
    assert not any(p.get("hotels") for p in _marker_payloads(events))


def test_date_reply_resumes_same_window_without_device_clock_rejection(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    import asyncio
    from datetime import date

    from b2c_concierge.profile import SessionProfile

    from .test_spine import _answer, _drive_in, _new_session

    class Clock:
        @staticmethod
        def now(tz):
            return NOW.astimezone(tz)
    monkeypatch.setattr(guard, "datetime", Clock)
    monkeypatch.setattr(agent_module, "reference_today", lambda _: date(2026, 10, 8))
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(
        city="Melbourne", client_timezone="America/Los_Angeles",
        timeslot_start="10:00", timeslot_end="14:00",
        requested_window={"start": "10:00", "end": "14:00"},
    )))
    scripted('{"family":"search","language":"en"}', response={
        "results": [CARD], "search_date": {"date": "2026-10-08"},
    })
    assert "Which date" in _answer(_drive_in(runner, session.id, "10am-2pm"))
    profile = asyncio.run(fake_profile_store.get(session.id))
    assert profile.requested_window == {"start": "10:00", "end": "14:00"}
    assert not profile.last_results  # rejected cards never become a selectable shortlist
    scripted('{"family":"search","language":"en"}', "Offers for tomorrow.", response={
        "results": [{**CARD, "offer_date": "2026-10-09"}], "search_date": {"date": "2026-10-09"},
    })
    events = _drive_in(runner, session.id, "Tomorrow please")
    assert _answer(events) == "Offers for tomorrow."
    profile = asyncio.run(fake_profile_store.get(session.id))
    assert profile.date == "2026-10-09"
    assert profile.requested_window == {"start": "10:00", "end": "14:00"}
    assert profile.last_results[0]["hotel_id"] == 1
