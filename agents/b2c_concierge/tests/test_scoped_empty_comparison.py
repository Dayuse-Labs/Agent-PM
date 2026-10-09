"""An empty price-filtered sample must never become global scarcity."""
import asyncio
import json

import pytest
from google.adk.runners import InMemoryRunner

from b2c_common.price_comparison import empty_comparison_notice
from b2c_concierge.agent import root_agent
from b2c_concierge.profile import SessionProfile
from .test_spine_profile import _scripted_llm, _new_session, _run_turn, fake_leg  # noqa: F401


@pytest.mark.parametrize('language', ['en', 'fr', 'es', 'it', 'de', 'pt', 'nl'])
def test_localized_comparison_keeps_actual_currency_and_total(language):
    assert '58.91 CAD' in empty_comparison_notice({'relation': 'lower', 'reference_minor': 5891, 'currency': 'CAD'}, language)
    assert '5891 JPY' in empty_comparison_notice({'relation': 'lower', 'reference_minor': 5891, 'currency': 'JPY'}, language)
    assert not empty_comparison_notice({'relation': 'lower', 'reference_minor': True, 'currency': 'EUR'}, language)


def test_empty_cheaper_search_does_not_enter_synthesis_or_relax_filters(monkeypatch, fake_leg, fake_profile_store):  # noqa: F811
    runner = InMemoryRunner(root_agent)
    session = _new_session(runner)
    comparison = {'relation': 'lower', 'currency': 'CAD', 'reference_minor': 5891}
    p = SessionProfile(city='Example City', requested_budget={}, price_comparison=comparison,
        requested_window={'start': '10:00', 'end': '17:00'}, timeslot_start='10:00', timeslot_end='17:00',
        amenities=['pool'], date='2026-10-12')
    asyncio.run(fake_profile_store.set(session.id, p))
    llm = _scripted_llm(monkeypatch, json.dumps({'family': 'search', 'language': 'en'}), 'NO OFFERS AT ALL')
    fake_leg.text = 'No offers at all.'
    fake_leg.response_payload = {'results': [], 'price_comparison': comparison,
        'search_context': {'city': p.city, 'date': p.date}, 'profile_delta': {},
        'area_coverage': {'unresolved_areas': ['Unresolved Place']}}
    answer = _run_turn(runner, session.id, 'Same constraints please')
    assert fake_leg.call_count == 1 and len(llm.calls) == 1
    assert 'strictly cheaper than 58.91 CAD' in answer and 'NO OFFERS AT ALL' not in answer
    assert 'does not mean that no offers are available' in answer
    assert 'Unresolved Place' in answer
    saved = asyncio.run(fake_profile_store.get(session.id))
    assert saved.price_comparison == comparison and saved.requested_window == p.requested_window
    assert saved.amenities == ['pool'] and saved.date == p.date and saved.requested_budget == {}
