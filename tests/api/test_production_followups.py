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


def test_region_extent_reconciles_provider_county_labels_without_accepting_distant_homonyms(monkeypatch):
    from hotel_search_agent import geocode_tool
    county = replace(place('Kent',kind='district'),country_code='GB',bbox=(0.03,50.89,1.47,51.48))
    client = SimpleNamespace(geocode_candidates=lambda *a, **k: [county])
    monkeypatch.setattr(geocode_tool,'get_mapbox_client',lambda:client)
    medway = replace(place('Gillingham',kind='place'),latitude=51.387,longitude=0.546,country_code='GB',region='England')
    assert geocode_tool._within_region_extent(medway,'Kent','GB','en')
    dorset = replace(medway,latitude=51.038,longitude=-2.276)
    assert not geocode_tool._within_region_extent(dorset,'Kent','GB','en')
    assert not geocode_tool._within_region_extent(medway,'Kent','US','en')


def test_verified_named_hotel_uses_provider_city_key_and_new_names_do_not_inherit_it():
    from google.genai import types
    from hotel_search_agent.response_bridge import encode_datapart,inject_verified_named_hotel
    known = {'hotel_id':11370,'name':'Rambler Oasis Hotel','city_name':'new-territories','source':'mcp_name_lookup'}
    ctx=SimpleNamespace(user_content=types.Content(parts=[encode_datapart({'query_params':{'named_hotel':known}})]))
    tool=SimpleNamespace(name='find_hotel_by_name')
    args={'name':'Rambler Oasis Hotel','cityName':'Hong Kong'}
    inject_verified_named_hotel(tool,args,ctx)
    assert args['cityName']=='new-territories'
    other={'name':'Other hotel','cityName':'London'}
    inject_verified_named_hotel(tool,other,ctx)
    assert other['cityName']=='London'


def test_named_area_can_use_exact_public_transport_anchor_but_not_business_homonym():
    station = place('La Défense', categories=('public_transportation_station','transportation'))
    restaurant = place('La Défense', categories=('restaurant',))
    sculpture = place('La Défense', categories=('public_artwork',))
    inventory = SimpleNamespace(count_near=lambda *a, **k: 100)
    assert rank_landmark([restaurant,sculpture,station],requested_zone='La Défense',inventory=inventory,location_kind='area') == station
    assert rank_landmark([restaurant,sculpture],requested_zone='La Défense',inventory=inventory,location_kind='area') is None


def test_exact_settlement_filter_keeps_provider_city_qualifier():
    from hotel_search_agent.geo_resolver import resolve
    metropolis = replace(place('New York City', kind='place'), latitude=40.7, country_code='US', region='New York')
    village = replace(place('New York', kind='locality'), latitude=30.0, country_code='US', region='Florida')
    unrelated = replace(place('New York Mills', kind='place'), latitude=44.0, country_code='US', region='Minnesota')
    inventory = SimpleNamespace(count_near=lambda lat, *a, **k: 100 if lat in {40.7,44.0} else 0)
    result = resolve([village,unrelated,metropolis],inventory=inventory,requested_name='New York',country_hint='US')
    assert result.chosen == metropolis
