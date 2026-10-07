"""Production failure mechanisms with controlled facts and adversarial outputs."""
from dataclasses import replace
from types import SimpleNamespace

import pytest
from b2c_concierge.profile import SessionProfile
from b2c_concierge.search_constraints import apply_search_update
from b2c_concierge.search_context import triage_search_context
from hotel_search_agent.geo_resolver import rank_landmark
from hotel_search_agent.mapbox_client import GeocodeCandidate
from hotel_search_agent.response_bridge import order_returned_offers


@pytest.mark.parametrize('action', ['retain', 'cheaper'])
@pytest.mark.parametrize('wrong_cap', [None, 200])
def test_cheaper_cannot_clear_or_raise_an_explicit_cap(action, wrong_cap):
    p = SessionProfile(budget_max=60, budget_request_source='explicit')
    apply_search_update(p, {'budget_max':wrong_cap}, action)
    assert p.budget_max == 60
    assert p.budget_request_source == 'explicit'


def test_explicit_budget_change_and_removal_still_work():
    p = SessionProfile(budget_max=60)
    apply_search_update(p, {'budget_max':100}, 'set')
    assert p.budget_max == 100
    apply_search_update(p, {'budget_max':None}, 'clear')
    assert p.budget_max is None


def test_language_and_stay_survive_more_turns_than_the_transcript():
    p = SessionProfile(language='en', locale='fr-FR', stay_kind='overnight', search_priority='distance')
    for _ in range(8):
        p = SessionProfile.from_dict(p.to_dict())
    c = triage_search_context(p)
    assert c['language'] == 'en'
    assert c['stay_kind'] == 'overnight'
    assert c['search_priority'] == 'distance'


def place(name, kind='poi', categories=()):
    return GeocodeCandidate(48.87,2.78,name,name,'France',kind,'FR','Ile-de-France',None,0,
                            poi_categories=categories)


def test_business_homonyms_do_not_become_the_requested_landmark():
    taxi = place('Taxi Disneyland Paris', categories=('taxi','transportation'))
    park = replace(place('Disneyland', categories=('theme_park','entertainment')), rank=8)
    inventory = SimpleNamespace(count_near=lambda *a, **k: 100)
    assert rank_landmark([taxi],requested_zone='Disneyland',inventory=inventory,location_kind='landmark') is None
    assert rank_landmark([taxi,park],requested_zone='Disneyland',inventory=inventory,location_kind='landmark') == park


def test_storage_business_does_not_resolve_an_administrative_area():
    storage = place('Homebox Rennes Sud', categories=('storage','services'))
    area = place('Rennes Sud', kind='neighborhood')
    inventory = SimpleNamespace(count_near=lambda *a, **k: 100)
    assert rank_landmark([storage],requested_zone='Rennes Sud',inventory=inventory,location_kind='area') is None
    assert rank_landmark([storage,area],requested_zone='Rennes Sud',inventory=inventory,location_kind='area') == area


def test_ordering_honors_the_requested_property_without_inventing_missing_values():
    rows = [{'hotel_id':1,'price_eur_cents':10000,'distance_km':8,'rating':9},
            {'hotel_id':2,'price_eur_cents':8000,'distance_km':2,'rating':8},
            {'hotel_id':3,'price_eur_cents':float('nan'),'distance_km':None}]
    for priority in ['price','distance']:
        assert [h['hotel_id'] for h in order_returned_offers(rows,priority)] == [2,1,3]
    assert order_returned_offers(rows,'rating') == rows
    assert order_returned_offers(rows,None) is rows
