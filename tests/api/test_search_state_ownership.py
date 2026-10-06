"""Regression boundaries: preserving turns, moves and A2A tool overrides."""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from a2a import types as a2a_types
from b2c_common.resolved_location import location_snapshot
from b2c_concierge.profile import SessionProfile
from b2c_concierge.search_constraints import apply_search_update, parse_search_update, protect_explicit_constraints
from b2c_concierge.search_context import prepare_search_context
from b2c_concierge.triage import _ground_location_update
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types as genai_types
from hotel_search_agent.budget_injection import inject_profile_budget
from hotel_search_agent.datetime_resolver import resolve_search_timeslot
from hotel_search_agent.geocode_tool import inject_profile_geo_context
from hotel_search_agent.response_bridge import capture_after_tool, inject_landmark_radius


def context(profile):
    part = a2a_types.Part(root=a2a_types.DataPart(data={"profile_in": profile, "query_params": {}}))
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=[
        genai_types.Part(text="100"), convert_a2a_part_to_genai_part(part),
    ]))


def committed():
    profile = SessionProfile(city="Berkeley", country_anchor="US", state_anchor="California")
    request = prepare_search_context(profile, {"action": "replace", "kind": "city", "city": "Berkeley",
        "country_code": "US", "region": "California"})['search_location_request']
    profile.resolved_search_location = location_snapshot(request, {
        "ok": True, "provider_place_id": "mapbox:berkeley-ca", "country_code": "US",
        "latitude": 37.87, "longitude": -122.27, "resolved_place": "Berkeley, California",
        "resolved_feature_type": "place", "distance_origin_type": "city_centroid",
        "profile_delta": {"last_state_context": "California"},
    })
    return SessionProfile.from_dict(profile.to_dict())


def test_budget_turn_reuses_provider_anchor_and_model_cannot_override_mcp_coordinates():
    profile = committed()
    # Stored state survives a roundtrip and more turns than the bounded transcript.
    for _ in range(6):
        view = prepare_search_context(profile, {"action": "retain"})
        ctx = context(view)
        result = inject_profile_geo_context(SimpleNamespace(name="geocode_location"), {"city": "Berkeley, Illinois"}, ctx)
        assert result['provider_place_id'] == 'mapbox:berkeley-ca'
        capture_after_tool(SimpleNamespace(name="geocode_location"), {}, ctx, result)
        args = {"lat": 41.88, "lon": -87.63}
        assert inject_landmark_radius(SimpleNamespace(name="search_offers"), args, ctx) is None
        assert (args['lat'], args['lon']) == (37.87, -122.27)
        profile = SessionProfile.from_dict(profile.to_dict())


@pytest.mark.parametrize('edit', [
    {"action": "replace", "city": "Paris", "country_code": "FR"},
    {"action": "refine", "zone": "Downtown", "kind": "area"},
    {"action": "refine", "region": "Illinois"},
])
def test_move_correction_or_area_change_invalidates_committed_anchor(edit):
    p = committed()
    view = prepare_search_context(p, edit)
    assert p.resolved_search_location is None
    assert 'resolved_search_location' not in view
    ctx = context(view)
    assert inject_profile_geo_context(SimpleNamespace(name="geocode_location"), {}, ctx) is None
    assert inject_landmark_radius(SimpleNamespace(name="search_offers"), {}, ctx)['error'] == 'geocode_required'


def test_different_borough_is_not_discarded_when_parent_was_classified_as_city():
    view = prepare_search_context(SessionProfile(), {'action':'replace','kind':'city','city':'New York City','zone':'Queens'})
    assert view['zone'] == 'Queens'
    assert view['search_location_request']['kind'] == 'area'


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), True, 95])
def test_invalid_provider_coordinates_are_never_reused(bad):
    p = committed()
    p.resolved_search_location['resolution']['latitude'] = bad
    assert 'resolved_search_location' not in prepare_search_context(p, {'action':'retain'})


def test_history_cannot_supply_evidence_for_a_location_edit_on_a_budget_turn():
    data = {'location_update':{'action':'replace','city':'Berkeley'},'location_evidence':'Berkeley'}
    assert _ground_location_update(data, '100') is None
    assert _ground_location_update(data, 'Hotel in Berkeley')['city'] == 'Berkeley'


def test_explicit_constraints_survive_a_timeout_and_contradictory_leaf_args():
    message = 'under 120 euros, from 08:30 to 17:00'
    update = parse_search_update({
        'budget_max':{'value':120,'currency':'EUR','evidence':'under 120 euros'},
        'timeslot_start':{'value':'08:30','evidence':'08:30'},
        'timeslot_end':{'value':'17:00','evidence':'17:00'},
    }, message)
    p = SessionProfile()
    apply_search_update(p, update)
    p = SessionProfile.from_dict(p.to_dict())  # no successful leaf response required
    ctx = context({**p.to_dict(),'constraint_edits_managed':True})
    args = {'priceRangeMax':180,'timeSlot':{'startHour':10,'endHour':18}}
    tool = SimpleNamespace(name='search_offers')
    inject_profile_budget(tool,args,ctx)
    resolve_search_timeslot(tool,args,ctx)
    assert args == {'priceRangeMax':120,'timeSlot':{'startHour':8,'endHour':17}}
    assert any(v == {'start_total':510,'end_total':1020} for v in ctx.state.values())
    delta = {'budget_max':180,'budget_request_source':'flexible_default','timeslot_start':'10:00','country_anchor':'FR'}
    assert protect_explicit_constraints(p, delta) == {'country_anchor':'FR'}


def test_explicit_removal_cannot_be_reintroduced_by_leaf():
    p = SessionProfile(budget_max=120,timeslot_start='08:30',timeslot_end='17:00')
    apply_search_update(p, {'budget_max':None,'timeslot_start':None,'timeslot_end':None})
    ctx = context({**p.to_dict(),'constraint_edits_managed':True})
    args = {'priceRangeMax':120,'timeSlot':{'startHour':8,'endHour':17}}
    tool = SimpleNamespace(name='search_offers')
    inject_profile_budget(tool,args,ctx)
    resolve_search_timeslot(tool,args,ctx)
    assert args == {}


def test_unknown_currency_and_absent_current_evidence_cannot_create_a_cap():
    assert parse_search_update({'budget_max':{'value':120,'currency':'USD','evidence':'120 dollars'}},'120 dollars') == {}
    assert parse_search_update({'budget_max':{'value':120,'evidence':'120 euros'}},'more options') == {}
    p = SessionProfile(timeslot_start='10:00',timeslot_end='17:00')
    before=deepcopy(p.to_dict())
    apply_search_update(p, {'timeslot_start':'23:00','timeslot_end':'06:00'})
    assert p.to_dict() == before


def test_provider_region_wins_over_a_negated_state_word():
    from hotel_search_agent.geocode_tool import _ok
    from hotel_search_agent.mapbox_client import GeocodeResult

    result = _ok(GeocodeResult(40.58, -74.41, 'South Plainfield, New Jersey', 'US',
        'New Jersey', provider_place_id='mapbox:south-plainfield-nj'), feature_type='place',
        profile_delta={'last_state_context':'NY'}, distance_origin_type='city_centroid')
    assert result['profile_delta']['last_state_context'] == 'New Jersey'


def test_durable_triage_context_contains_filters_even_after_history_rolls_off():
    from b2c_concierge.search_context import triage_search_context

    p = committed()
    p.timeslot_start, p.timeslot_end = '16:00', '22:00'
    p.budget_max = 150
    p.last_results = [{'hotel_id':7,'name':'Example Hotel','price':100,'latitude':37}]
    state = triage_search_context(SessionProfile.from_dict(p.to_dict()))
    assert state['timeslot_end'] == '22:00' and state['budget_max'] == 150
    assert state['visible_hotels'] == [{'hotel_id':7,'name':'Example Hotel'}]
    assert 'resolved_search_location' not in state


def test_priced_offer_mismatch_is_visible_even_if_synthesis_ignores_leaf_warning():
    from b2c_concierge.result_constraints import annotate_constraints, constraint_notice

    p = SessionProfile(budget_max=80,budget_request_source='explicit', timeslot_start='10:00',
        timeslot_end='17:00',timeslot_request_source='explicit')
    response = {'results':[{'price_eur_cents':9000,'timeslots':[{'start':'10:00','end':'16:00'}]}]}
    assert annotate_constraints(response,p) == ['budget','hours']
    assert 'alternatives' in constraint_notice(response,'fr')
    response = {'results':[{'price_eur_cents':7500,'timeslots':[{'start':'09:00','end':'18:00'}]}]}
    assert annotate_constraints(response,p) == []
    assert constraint_notice(response,'en') == ''


def test_wire_location_refinement_distinguishes_unchanged_from_explicit_clear():
    edit = _ground_location_update({
        'location_evidence': 'Downtown',
        'location_update': {'action': 'refine', 'kind': 'area', 'fields': [
            {'field': 'zone', 'value': 'Downtown'}, {'field': 'metro', 'value': None},
        ]},
    }, 'Downtown please')
    view = prepare_search_context(committed(), edit)
    assert view['search_location_request']['city'] == 'Berkeley'
    assert view['search_location_request']['zone'] == 'Downtown'
    assert view['search_location_request']['metro'] is None
    assert _ground_location_update({'location_update': {'action': 'retain', 'kind': None, 'fields': []}}, '100') == {'action': 'retain'}


def test_strict_generation_contract_rejects_observed_nested_location_and_missing_evidence():
    from jsonschema import Draft202012Validator
    from b2c_concierge.triage import BOOKING_CONFIRMATIONS, FAMILIES, LANGUAGES, PICKS
    from b2c_concierge.triage_schema import response_format
    schema = response_format(FAMILIES, LANGUAGES, PICKS, BOOKING_CONFIRMATIONS)['json_schema']['schema']
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema['properties']['search_update'])
    # These two actual malformed generations used to silently discard the edit.
    assert list(validator.iter_errors({'location_update': {'action': 'replace'}, 'location_evidence': 'station'}))
    assert list(validator.iter_errors({'budget_max': {'value': 95, 'currency': 'EUR'}, 'timeslot_start': None, 'timeslot_end': None}))
    assert not list(validator.iter_errors({'budget_max': {'value': 95, 'currency': 'EUR', 'evidence': '95€'}, 'timeslot_start': None, 'timeslot_end': None}))


def test_wire_contract_cannot_mix_retention_with_a_new_location_kind():
    from jsonschema import Draft202012Validator
    from b2c_concierge.triage import BOOKING_CONFIRMATIONS, FAMILIES, LANGUAGES, PICKS
    from b2c_concierge.triage_schema import response_format
    schema = response_format(FAMILIES, LANGUAGES, PICKS, BOOKING_CONFIRMATIONS)['json_schema']['schema']
    validator = Draft202012Validator(schema['properties']['location_update'])
    assert not list(validator.iter_errors({'action': 'retain'}))
    assert list(validator.iter_errors({'action': 'retain', 'kind': 'area', 'fields': []}))
