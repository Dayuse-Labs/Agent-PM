"""An empty containment search must not propose a stricter stay as recovery."""
import asyncio

import pytest

from b2c_concierge.profile import SessionProfile

from .test_spine import _answer, _drive_in, _new_session, scripted  # noqa: F401


@pytest.mark.parametrize("widen", [None, {"from": 100, "to": 120}])
def test_empty_full_stay_uses_bounded_recovery_without_inventing_times(scripted, fake_profile_store, widen):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Wien", date="2026-11-01", language="de", locale="de",
        auto_widen_disclosure=widen,
        timeslot_start="13:00", timeslot_end="18:00", requested_window={"start": "13:00", "end": "18:00"})))
    llm, _ = scripted('{"family":"search","language":"de","requested_budget":null}',
        'Versuche 12:00–19:00.', response={"results": [], "search_date": {"date": "2026-11-01"},
        "search_context": {"city": "Wien", "date": "2026-11-01", "timeslot_start": "13:00", "timeslot_end": "18:00"}})
    answer = _answer(_drive_in(runner, session.id, "1300 - 1800"))
    assert "12:00–19:00" not in answer
    assert "spätere Ankunft" in answer and "frühere Abreise" in answer
    assert len(llm.calls) == 1  # triage; no synthesis of an invented alternative
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.requested_window == {"start": "13:00", "end": "18:00"}
    assert saved.auto_widen_disclosure is None
    if widen:
        assert "100 €" in answer and "120 €" in answer


def test_faq_keeps_its_evidence_answer_with_a_carried_window(scripted, fake_profile_store):  # noqa: F811
    runner, session = _new_session()
    asyncio.run(fake_profile_store.set(session.id, SessionProfile(city="Wien",
        requested_window={"start": "13:00", "end": "18:00"})))
    llm, _ = scripted('{"family":"faq","language":"en"}', 'See the cancellation terms of your offer.',
        leaf_text='See the cancellation terms of your offer.', response={})
    answer = _answer(_drive_in(runner, session.id, "What are the cancellation terms?"))
    assert answer == 'See the cancellation terms of your offer.'
    assert len(llm.calls) == 2
