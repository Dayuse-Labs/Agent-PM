"""A zero-inventory reply cites the combined search, not budget alone."""
import asyncio
import json

import b2c_concierge.agent as module
from b2c_concierge.profile import SessionProfile, record_search_outcome

from .test_spine import _drive_in, _new_session, scripted  # noqa: F401


def test_budget_window_empty_response_preserves_executed_context(scripted, monkeypatch, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    profile = SessionProfile(city="Example City", date="2027-01-12",
        requested_budget={"amount": 150, "currency": "USD", "unit": "total"},
        requested_window={"start": "10:30", "end": "19:00"}, timeslot_start="10:30", timeslot_end="19:00")
    asyncio.run(fake_profile_store.set(session.id, profile))
    scripted(json.dumps({"family": "search", "language": "en", "location_update": {"action": "preserve"}}))
    async def leaf(*args, **kwargs):
        return "Increase the budget", {"results": [], "search_context": {
            "city": "Example City", "zone": "160 Example Street", "date": "2027-01-12",
            "timeslot_start": "10:30", "timeslot_end": "19:00", "budget_max": None,
            "amenities": ["pool"], "adults": 2,
        }}
    monkeypatch.setattr(module, "_run_leaf", leaf)
    events = _drive_in(runner, session.id, "same place and hours please")
    answer = " ".join(p.text for e in events if e.content for p in e.content.parts if p.text)
    assert all(s in answer for s in ["160 Example Street", "Example City", "2027", "10:30", "19:00", "150 USD", "booking fees", "pool"])
    assert "Increase the budget" not in answer
    after = asyncio.run(fake_profile_store.get(session.id))
    assert after.requested_window == profile.requested_window
    assert after.requested_budget == profile.requested_budget
    assert after.last_suggestions == ["try another date", "try a nearby area", "adjust the hours"]


def test_window_recovery_does_not_override_closed_day_or_survive_success():
    profile = SessionProfile()
    record_search_outcome(profile, 0, window_constrained=True, same_day_dead_end=True)
    assert profile.last_suggestions[0] == "see tomorrow"
    record_search_outcome(profile, 1, window_constrained=True)
    assert profile.last_suggestions is None
