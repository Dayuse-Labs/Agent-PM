"""Area requests need provider identity and per-hotel membership, not a disc."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from google.genai import types
from b2c_concierge.profile import SessionProfile, apply_profile_delta
from hotel_search_agent.area_scope import (
    STATE_AREAS, STATE_COVERAGE, resolve_areas, search_areas_before_tool, validate_areas,
)
from hotel_search_agent.geocode_tool import inject_profile_geo_context
from hotel_search_agent.mapbox_client import GeocodeCandidate, MapboxClient
from hotel_search_agent.response_bridge import (
    capture_after_tool, encode_datapart, emit_search_datapart, decode_datapart,
)

AREAS = [
    {"query": "Yvelines", "kind": "administrative", "country": "FR", "code": "78", "evidence": "78"},
    {"query": "Hauts-de-Seine", "kind": "administrative", "country": "FR", "code": "92", "evidence": "92"},
]


@pytest.mark.parametrize("query,message,country", [
    ("Île-de-France", "En île de France avec spa", "FR"),
    ("Hauts-de-Seine", "dans les Hauts de Seine", "FR"),
    ("São Paulo", "Sao Paulo seulement", "BR"),
])
def test_area_identity_allows_typography_with_current_literal_evidence(query, message, country):
    area = {"query": query, "kind": "administrative", "country": country, "evidence": message}
    assert validate_areas([area], message) == [area]


@pytest.mark.parametrize("query,message", [("York", "Yorkshire"), ("Paris", "Parish"), ("", "Paris")])
def test_area_identity_requires_whole_name_not_a_substring(query, message):
    area = {"query": query, "kind": "municipality", "country": "GB", "evidence": message}
    assert validate_areas([area], message) is None


@pytest.mark.parametrize("city,zone", [("Arcadia City", "City"), ("Ho Chi Minh City", "City"), ("Paris", "Paris")])
def test_owned_city_component_does_not_become_a_separate_landmark(city, zone):
    ctx = context({'city': city, 'country_anchor': 'US'}, 'a room in ' + city)
    ctx.user_content.parts[1] = encode_datapart({
        'profile_in': {'city': city, 'country_anchor': 'US'},
        'query_params': {'areas_authoritative': True},
    })
    args = {'city': city, 'zone': zone}
    assert inject_profile_geo_context(SimpleNamespace(name='geocode_location'), args, ctx) is None
    assert args['city'] == city
    assert 'zone' not in args


@pytest.mark.parametrize('model_message', [None, 'Arcadia', 'Arcadia in Michigan'])
def test_geocoder_receives_actual_message_including_explicit_state(model_message):
    message = 'A room in Arcadia City, California'
    ctx = context({'city': 'Arcadia City', 'country_anchor': 'US'}, message)
    args = {'city': 'Arcadia City'}
    if model_message is not None:
        args['raw_user_message'] = model_message
    inject_profile_geo_context(SimpleNamespace(name='geocode_location'), args, ctx)
    assert args['raw_user_message'] == message


def candidate(name="Yvelines", code="78", ident="area78", **kwargs):
    return GeocodeCandidate(48.8, 1.8, name, name, "France", "region", "FR", name,
                            (1.44, 48.43, 2.23, 49.09), 0, ident, code, **kwargs)


def client():
    return SimpleNamespace(geocode_candidates=lambda query, **kw: [candidate() if query == "Yvelines" else candidate("Hauts-de-Seine", "92", "area92")])


@pytest.mark.parametrize('bounded_city', [False, True])
def test_city_search_cannot_return_hotels_outside_required_region(monkeypatch, bounded_city):
    city = replace(candidate(), name='Melun', feature_type='place', mapbox_id='melun',
                   place_name='Melun, Seine-et-Marne, France', region='Seine-et-Marne',
                   bbox=(2.63, 48.51, 2.69, 48.56))
    # The parent region need not have a usable/within-200km bbox: only its
    # identity is required when retrieving around the confirmed city.
    region = replace(candidate(), name='Seine-et-Marne', mapbox_id='dept77', bbox=None)
    provider = SimpleNamespace(geocode_candidates=lambda q, **kw: [region if q == 'Seine-et-Marne' else city],
        containing_area_ids=lambda lat, lon: {1: {'melun', 'dept77'}, 2: {'dept91'}, 3: {'dept77'}}[int(lat)])
    item = {'query': 'Melun', 'kind': 'municipality', 'country': 'FR', 'evidence': 'Melun',
            'region': 'Seine-et-Marne', 'required_region': 'Seine-et-Marne'}
    if bounded_city:
        item['boundary_evidence'] = 'only Melun'
    resolved = resolve_areas([item], provider)
    assert resolved['ok']
    area = resolved['search_areas'][0]
    assert area['latitude'] > 48 and area['radius_km'] <= 20
    monkeypatch.setattr('hotel_search_agent.geocode_tool.get_mapbox_client', lambda: provider)
    sent = []
    async def run_async(*, args, tool_context):
        sent.append(args)
        return {'structuredContent': {'results': [{'hotelId': i, 'lat': i, 'lon': 2} for i in (1, 2, 3)]}}
    ctx = context(state={STATE_AREAS: resolved['search_areas']})
    result = asyncio.run(search_areas_before_tool(SimpleNamespace(name='search_offers', run_async=run_async), {}, ctx))
    assert [h['hotelId'] for h in result['structuredContent']['results']] == ([1] if bounded_city else [1, 3])
    assert sent[0]['lat'] > 48  # City retrieval, not the department's centroid.


def context(profile=None, message="78 ou 92", state=None):
    return SimpleNamespace(state=state or {}, user_content=types.Content(role="user", parts=[
        types.Part(text=message), encode_datapart({"profile_in": profile or {}}),
    ]))


def test_provider_codes_and_bounding_circle_cover_the_whole_requested_areas():
    result = resolve_areas(AREAS, client())
    assert result["ok"]
    assert [a["id"] for a in result["search_areas"]] == ["area78", "area92"]
    assert result["search_areas"][0]["radius_km"] > 40
    assert result["profile_delta"]["search_areas"] == AREAS


def test_country_is_resolved_from_provider_identity_before_requesting_parent():
    provider = SimpleNamespace(geocode_candidates=lambda *a, **kw: [candidate()])
    result = resolve_areas([{'query': 'Yvelines', 'kind': 'administrative',
                            'country': '', 'evidence': 'Yvelines'}], provider)
    assert result['ok'] and result['search_areas'][0]['country'] == 'FR'
    assert result['search_areas'][0]['id'] == 'area78'


def test_administrative_code_alone_cannot_select_a_country():
    def no_lookup(*args, **kwargs):
        raise AssertionError('A local administrative code has no global identity')
    result = resolve_areas([{**AREAS[0], 'country': ''}], SimpleNamespace(geocode_candidates=no_lookup))
    assert result['error'] == 'area_parent_needed'


@pytest.mark.parametrize('gap,accepted', [(1, False), (2, False), (3, True), (7, True)])
def test_area_homonyms_use_provider_identity_confidence(gap, accepted):
    leading = candidate()
    other = replace(leading, mapbox_id='other', rank=gap, country_code='CA', latitude=45.5)
    provider = SimpleNamespace(geocode_candidates=lambda *a, **kw: [leading, other])
    request = {k: v for k, v in {**AREAS[0], 'country': ''}.items() if k != 'code'}
    result = resolve_areas([request], provider)
    assert result['ok'] is accepted
    if accepted:
        assert result['search_areas'][0]['id'] == 'area78'


def test_provider_prominence_never_overrides_explicit_area_country():
    leading = candidate()
    other = replace(leading, mapbox_id='other', rank=7, country_code='CA')
    provider = SimpleNamespace(geocode_candidates=lambda *a, **kw: [leading, other])
    result = resolve_areas([{**AREAS[0], 'country': 'CA'}], provider)
    assert result['ok'] and result['search_areas'][0]['id'] == 'other'


@pytest.mark.parametrize('parent_name', ['New York', 'New York City'])
def test_child_provider_relationship_resolves_parent_without_separate_homonym_choice(parent_name):
    child = replace(candidate('Manhattan', '', 'manhattan'), feature_type='locality',
                    country_code='US', parent_city_name=parent_name, parent_city_id='nyc',
                    parent_ids=('nyc', 'state-ny'), bbox=(-74.02, 40.7, -73.9, 40.88))
    calls = []
    def geocode(query, **kwargs):
        calls.append(query)
        return [child]
    item = {'query': 'New York', 'subarea': 'Manhattan', 'kind': 'municipality',
            'country': 'US', 'evidence': 'New York'}
    result = resolve_areas([item], SimpleNamespace(geocode_candidates=geocode))
    assert result['ok'] and calls == ['Manhattan, New York']
    assert result['search_areas'][0]['id'] == 'manhattan'
    assert result['search_areas'][0]['required_parent_id'] == 'nyc'


@pytest.mark.parametrize('change', [
    {'parent_city_name': 'West New York'}, {'parent_ids': ('other-city',)},
    {'country_code': 'CA'}, {'name': 'Manhattan Hotel'}, {'feature_type': 'poi'},
])
def test_child_identity_cannot_guess_a_parent_from_name_or_proximity(change):
    child = replace(candidate('Manhattan', '', 'manhattan'), feature_type='locality',
                    country_code='US', parent_city_name='New York City', parent_city_id='nyc',
                    parent_ids=('nyc',), bbox=(-74.02, 40.7, -73.9, 40.88))
    provider = SimpleNamespace(geocode_candidates=lambda *a, **kw: [replace(child, **change)])
    result = resolve_areas([{'query': 'New York', 'subarea': 'Manhattan', 'kind': 'municipality',
                            'country': 'US', 'evidence': 'New York'}], provider)
    assert not result['ok'] and result['error'] == 'area_subarea_unresolved'


@pytest.mark.parametrize("changed", [
    {"country_code": "US"}, {"feature_type": "place"}, {"mapbox_id": ""},
    {"administrative_code": "75"}, {"bbox": None}, {"bbox": (2, 49, 1, 48)},
])
def test_wrong_country_kind_identifier_code_or_boundary_cannot_become_area(changed):
    fake = SimpleNamespace(geocode_candidates=lambda *a, **k: [replace(candidate(), **changed)])
    assert not resolve_areas(AREAS[:1], fake)["ok"]


def test_state_too_large_is_not_silently_clipped_to_200km():
    fake = SimpleNamespace(geocode_candidates=lambda *a, **k: [replace(candidate(), bbox=(-83.4, 31.9, -78.4, 35.3))])
    result = resolve_areas(AREAS[:1], fake)
    assert result["error"] == "area_exceeds_search_radius"
    assert result["profile_delta"]["search_areas"] == AREAS[:1]


def test_unresolved_alternative_does_not_discard_a_verified_requested_area():
    requests = [AREAS[0], {"query": "near Yvelines", "kind": "administrative",
                          "country": "FR", "evidence": "near Yvelines"}]
    provider = SimpleNamespace(geocode_candidates=lambda query, **kw: [candidate()] if query == "Yvelines" else [])
    result = resolve_areas(requests, provider)
    assert result['ok']
    assert [a['id'] for a in result['search_areas']] == ['area78']
    assert result['unresolved_areas'] == [{'query': 'near Yvelines', 'error': 'area_unresolved'}]
    assert result['profile_delta']['search_areas'] == requests


def test_partial_area_search_keeps_unresolved_scope_in_coverage(monkeypatch):
    from hotel_search_agent.area_scope import STATE_RESOLUTION
    ctx = context(state={STATE_AREAS: [{'id': 'area78', 'label': 'Yvelines', 'country': 'FR',
                                       'latitude': 48.8, 'longitude': 1.8, 'radius_km': 70}],
                         STATE_RESOLUTION: {'unresolved_areas': [{'query': 'near Yvelines', 'error': 'area_unresolved'}]}})
    monkeypatch.setattr('hotel_search_agent.geocode_tool.get_mapbox_client', lambda: SimpleNamespace())
    async def run_async(*, args, tool_context):
        return {'structuredContent': {'results': []}}
    result = asyncio.run(search_areas_before_tool(SimpleNamespace(name='search_offers', run_async=run_async), {}, ctx))
    assert result['structuredContent']['areaCoverage']['unresolved_areas'] == ['near Yvelines']
    assert ctx.state[STATE_COVERAGE]['exhaustive'] is False


@pytest.mark.parametrize("value", [None, [], AREAS * 3, [{**AREAS[0], "latitude": "48"}],
                                      [{**AREAS[0], "code": "75"}], [{**AREAS[0], "evidence": "77"}]])
def test_invalid_or_unquoted_area_cannot_set_scope(value):
    assert validate_areas(value, "78 ou 92") is None


def test_null_optional_code_keeps_named_province_and_provider_resolution():
    # Triage can emit JSON null for an optional code on a named province.
    # Discarding the entire extraction silently sends the leaf to a city search.
    area = {"query": "Brescia", "kind": "administrative", "country": "IT",
            "evidence": "Brescia e provincia", "code": None}
    validated = validate_areas([area], "Un hotel a Brescia e provincia")
    assert validated == [{k: v for k, v in area.items() if k != "code"}]
    provider = SimpleNamespace(geocode_candidates=lambda *a, **kw: [
        replace(candidate(), name="Brescia", country_code="IT", mapbox_id="province-bs")
    ])
    assert resolve_areas(validated, provider)["search_areas"][0]["id"] == "province-bs"


@pytest.mark.parametrize("code", [78, False])
def test_non_string_non_null_code_still_rejected(code):
    assert validate_areas([{**AREAS[0], "code": code}], "78") is None


def test_area_roundtrip_and_city_change_preserve_budget_date_and_amenities():
    profile = SessionProfile(search_areas=AREAS, city="Yvelines / Hauts-de-Seine", date="2026-10-10", amenities=["jacuzzi"], budget_max=150)
    assert SessionProfile.from_dict(profile.to_dict()).search_areas == AREAS
    apply_profile_delta(profile, {"city": "Lyon"}, "Et Lyon ?")
    assert profile.search_areas is None
    assert (profile.date, profile.amenities, profile.budget_max) == ("2026-10-10", ["jacuzzi"], 150)


def test_followup_scope_comes_from_profile_and_forged_message_is_rejected(monkeypatch):
    monkeypatch.setattr("hotel_search_agent.geocode_tool.get_mapbox_client", client)
    tool = SimpleNamespace(name="geocode_location")
    carried = inject_profile_geo_context(tool, {}, context({"search_areas": AREAS, "city": "Yvelines / Hauts-de-Seine"}, "Moins cher"))
    assert carried["ok"] and len(carried["search_areas"]) == 2
    forged = inject_profile_geo_context(tool, {"areas": AREAS, "raw_user_message": "78 ou 92"}, context(message="Lyon"))
    assert forged["error"] == "invalid_area_request"
    assert inject_profile_geo_context(tool, {"city": "Lyon"}, context({"search_areas": AREAS, "city": "Yvelines / Hauts-de-Seine"}, "Lyon")) is None


def test_reverse_membership_uses_provider_ids_including_alternate_levels():
    def handle(request):
        assert request.url.path.endswith("/reverse")
        return httpx.Response(200, json={"features": [{"properties": {"mapbox_id": "place", "context": {
            "region": {"mapbox_id": "area78", "alternate": {"mapbox_id": "idf"}},
        }}}]})
    c = MapboxClient("test", client=httpx.Client(transport=httpx.MockTransport(handle)))
    assert c.containing_area_ids(48.8, 2.1) == {"place", "area78", "idf"}


def test_reverse_membership_keeps_provider_semantic_identity_without_name_fallback():
    payload = {'features': [{'properties': {'mapbox_id': 'different-reverse-id',
                  'context': {'region': {'mapbox_id': 'department', 'alternate': {
                      'mapbox_id': 'alternate-region-id', 'name': 'Same Region', 'wikidata_id': 'Q123'}}}}}]}
    c = MapboxClient('test', client=httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload))))
    assert 'wikidata:Q123' in c.containing_area_ids(48.8, 2.1)


@pytest.mark.parametrize('own_context,expected', [({'wikidata_id': 'Q123'}, 'Q123'), ({}, '')])
def test_forward_identity_comes_from_the_feature_itself_not_its_parent_country(own_context, expected):
    payload = {'features': [{'geometry': {'coordinates': [2.1, 48.8]}, 'properties': {
        'name': 'Region', 'feature_type': 'region', 'mapbox_id': 'forward',
        'context': {'region': own_context, 'country': {'country_code': 'FR', 'wikidata_id': 'Q142'}}}}]}
    assert MapboxClient._parse_candidates(payload)[0].wikidata_id == expected


def test_provider_semantic_identity_joins_forward_and_reverse_variants(monkeypatch):
    from dataclasses import asdict
    forward = SimpleNamespace(**{**asdict(candidate()), 'wikidata_id': 'Q123'})
    resolved = resolve_areas(AREAS[:1], SimpleNamespace(geocode_candidates=lambda *a, **kw: [forward]))
    ctx = context()
    capture_after_tool(SimpleNamespace(name='geocode_location'), {}, ctx, resolved)
    reverse = SimpleNamespace(containing_area_ids=lambda lat, lon: {'different-id', 'wikidata:Q123' if lat == 48.8 else 'wikidata:Q999'})
    monkeypatch.setattr('hotel_search_agent.geocode_tool.get_mapbox_client', lambda: reverse)
    async def run_async(*, args, tool_context):
        return {'structuredContent': {'results': [{'hotelId': 1, 'lat': 48.8, 'lon': 2.1},
                                                  {'hotelId': 2, 'lat': 47.8, 'lon': 2.1}]}}
    result = asyncio.run(search_areas_before_tool(SimpleNamespace(name='search_offers', run_async=run_async), {}, ctx))
    assert [h['hotelId'] for h in result['structuredContent']['results']] == [1]


def test_batch_filters_paris_and_unknowns_keeps_both_areas_and_all_filters(monkeypatch):
    calls = []
    def hotel(i):
        return {"hotelId": i, "name": str(i), "lat": 48 + i / 100, "lon": 2,
                "offers": [{"priceEuro": 9900, "startHour": 10, "endHour": 18}]}
    async def run_async(*, args, tool_context):
        calls.append(dict(args))
        ids = [1, 2, 3] if len(calls) == 1 else [4, 5, 1]
        return {"structuredContent": {"results": [hotel(i) for i in ids]}}
    c = SimpleNamespace(containing_area_ids=lambda lat, lon: {1: {"area75"}, 2: {"area78"}, 3: None, 4: {"area92"}, 5: {"area92"}}[round((lat-48)*100)])
    monkeypatch.setattr("hotel_search_agent.geocode_tool.get_mapbox_client", lambda: c)
    resolved = resolve_areas(AREAS, client())
    ctx = context()
    capture_after_tool(SimpleNamespace(name="geocode_location"), {}, ctx, resolved)
    args = {"date": "2026-10-10", "priceRangeMax": 150, "hotelEquipmentIds": [41], "adults": 2,
            "timeSlot": {"startHour": 10, "endHour": 17}, "lat": 0, "lon": 0}
    tool = SimpleNamespace(name="search_offers", run_async=run_async)
    result = asyncio.run(search_areas_before_tool(tool, args, ctx))
    rows = result["structuredContent"]["results"]
    assert {h["hotelId"] for h in rows} == {2, 4, 5}
    assert len(calls) == 2
    assert all(c["date"] == args["date"] and c["hotelEquipmentIds"] == [41] and c["priceRangeMax"] == 150
               and c["timeSlot"] == args["timeSlot"] and c["adults"] == 2 for c in calls)
    assert all(c["lat"] != 0 and c["size"] == 5 and c["radiusKm"] > 20 for c in calls)
    assert ctx.state[STATE_COVERAGE]["unverified"] == 1
    compact = capture_after_tool(tool, calls[0], ctx, result)
    assert all(c["verified_search_areas"] for c in compact["hotels"])
    assert all("distance_km" not in c for c in compact["hotels"])
    assert search_areas_before_tool(tool, args, ctx)["ok"] is False
    assert len(calls) == 2
    event = emit_search_datapart(ctx)
    data = next(decode_datapart(p) for p in event.parts if decode_datapart(p))
    assert data["area_coverage"]["exhaustive"] is False
    profile = SessionProfile(city="Paris", zone="Centre", amenities=["jacuzzi"])
    apply_profile_delta(profile, data["profile_delta"], "78 ou 92")
    assert profile.search_areas == AREAS and profile.zone is None
    assert profile.city == "Yvelines / Hauts-de-Seine"


def test_failed_fresh_geocode_revokes_previous_scope():
    ctx = context(state={STATE_AREAS: [{"id": "old"}]})
    capture_after_tool(SimpleNamespace(name="geocode_location"), {}, ctx, {"ok": False})
    assert ctx.state[STATE_AREAS] is None


def test_numeric_evidence_itself_is_the_provider_code_without_a_model_copy():
    value = [{k: v for k, v in a.items() if k != 'code'} for a in AREAS]
    assert [a['code'] for a in validate_areas(value, 'île de france 78 ou 92')] == ['78', '92']


def test_exact_named_area_is_sufficient_when_model_paraphrases_the_quote():
    value = [{'query': 'Hauts-de-Seine', 'kind': 'administrative', 'country': 'FR',
              'evidence': 'dans les Hauts-de-Seine'}]
    result = validate_areas(value, 'dans les Yvelines ou les Hauts-de-Seine')
    assert result is not None and result[0]['evidence'] == 'Hauts-de-Seine'


def test_tool_schema_requires_query_and_exposes_the_closed_area_kinds():
    from google.adk.tools import FunctionTool
    from hotel_search_agent.geocode_tool import geocode_location
    declaration = FunctionTool(geocode_location)._get_declaration()
    schema = declaration.parameters_json_schema
    definitions = schema.get('$defs', {})
    item = schema['properties']['areas']['anyOf'][0]['items']
    if '$ref' in item:
        item = definitions[item['$ref'].split('/')[-1]]
    assert 'query' in item['required']
    assert item['properties']['kind']['enum'] == ['administrative', 'municipality', 'neighborhood']


def test_failed_area_resolution_cannot_retry_as_its_parent_city(monkeypatch):
    monkeypatch.setattr('hotel_search_agent.geocode_tool.get_mapbox_client', lambda: SimpleNamespace(geocode_candidates=lambda *a, **k: []))
    ctx = context()
    tool = SimpleNamespace(name='geocode_location')
    failed = inject_profile_geo_context(tool, {'areas': AREAS}, ctx)
    assert failed['ok'] is False
    second = inject_profile_geo_context(tool, {'city': 'Paris'}, ctx)
    assert second is not None and second['ok'] is False


def test_authoritative_profile_beats_parallel_blank_or_wrong_leaf_extraction(monkeypatch):
    monkeypatch.setattr('hotel_search_agent.geocode_tool.get_mapbox_client', client)
    ctx = context({'city': 'Yvelines / Hauts-de-Seine', 'search_areas': AREAS})
    ctx.user_content.parts[-1] = encode_datapart({'profile_in': {'city': 'Yvelines / Hauts-de-Seine', 'search_areas': AREAS},
                                                'query_params': {'areas_authoritative': True}})
    result = inject_profile_geo_context(SimpleNamespace(name='geocode_location'), {'city': 'Paris', 'areas': [{'city': 'Paris'}]}, ctx)
    assert result['ok'] and len(result['search_areas']) == 2


def test_copying_prior_area_on_non_geographic_followup_is_not_fresh_evidence(monkeypatch):
    monkeypatch.setattr('hotel_search_agent.geocode_tool.get_mapbox_client', client)
    ctx = context({'city': 'Yvelines / Hauts-de-Seine', 'search_areas': AREAS}, 'Sans le jacuzzi, garde le reste.')
    result = inject_profile_geo_context(SimpleNamespace(name='geocode_location'), {'areas': AREAS}, ctx)
    assert result['ok'] and len(result['search_areas']) == 2


def test_localized_province_label_resolves_but_a_different_province_does_not():
    req = [{'query': 'Brescia e provincia', 'kind': 'administrative', 'country': 'IT', 'evidence': 'Brescia'}]
    p = replace(candidate(), name='provincia di Brescia', country_code='IT', administrative_code='BS', mapbox_id='brescia-region')
    fake = SimpleNamespace(geocode_candidates=lambda *a, **k: [p])
    assert resolve_areas(req, fake, 'it')['ok']
    p = replace(p, name='provincia di Mantova')
    assert not resolve_areas(req, fake, 'it')['ok']


def test_generic_followup_quote_cannot_change_a_province_to_a_city():
    request = [{'query': 'Brescia', 'kind': 'municipality', 'country': 'IT', 'evidence': 'Tutte'}]
    assert validate_areas(request, 'Tutte') is None


def test_direction_qualifier_is_not_discarded_when_verifying_an_area_name():
    req = [{'query': 'South Carolina', 'kind': 'administrative', 'country': 'US', 'evidence': 'South Carolina'}]
    p = replace(candidate(), name='North Carolina', country_code='US')
    assert not resolve_areas(req, SimpleNamespace(geocode_candidates=lambda *a, **k: [p]))['ok']


def test_redundant_geocodes_reuse_the_verified_plan_before_budget_can_erase_it(monkeypatch):
    from hotel_search_agent.tool_budget_guard import make_per_tool_budget_callback
    from hotel_search_agent.response_bridge import enforce_resolved_search_origin
    ctx = context()
    ctx.invocation_id = 'one-user-turn'
    tool = SimpleNamespace(name='geocode_location')
    cap = make_per_tool_budget_callback({'geocode_location': 2}, 2)
    assert cap(tool, {}, ctx) is None
    resolved = resolve_areas(AREAS, client())
    capture_after_tool(tool, {}, ctx, resolved)
    for _ in range(3):
        reused = cap(tool, {'city': ''}, ctx)
        assert reused == resolved
        capture_after_tool(tool, {}, ctx, reused)
    args = {}
    assert enforce_resolved_search_origin(SimpleNamespace(name='search_offers'), args, ctx) is None
    assert args['lat'] == resolved['latitude']
    assert ctx.state['_per_tool_budget_counts']['geocode_location'] == 1


def test_boundary_requires_explicit_change_but_a_new_city_is_allowed():
    from b2c_common.search_areas import preserve_area_boundary
    old = [{'query': 'Brescia', 'kind': 'administrative', 'country': 'IT', 'evidence': 'Brescia e provincia'}]
    repeated = [{'query': 'Brescia', 'kind': 'municipality', 'country': 'IT', 'evidence': 'Brescia Italia'}]
    assert preserve_area_boundary(old, repeated) == old
    narrowed = [{**repeated[0], 'boundary_evidence': 'solo in città'}]
    assert preserve_area_boundary(old, narrowed) == narrowed
    lyon = [{'query': 'Lyon', 'kind': 'municipality', 'country': 'FR', 'evidence': 'Lyon'}]
    assert preserve_area_boundary(old, lyon) == lyon


def test_single_city_without_boundary_quote_uses_normal_city_geocoding():
    args = {'areas': [{'query': 'Paris', 'kind': 'municipality', 'country': 'FR', 'evidence': 'Paris'}]}
    result = inject_profile_geo_context(SimpleNamespace(name='geocode_location'), args, context(message='Un hôtel à Paris'))
    assert result is None
    assert args['city'] == 'Paris' and args['country_code'] == 'FR'
    assert 'areas' not in args


def test_authoritative_ordinary_city_cannot_be_replaced_by_leaf_boundary():
    ctx = context({'city': 'Paris', 'country_anchor': 'FR'}, 'Paris')
    ctx.user_content.parts[-1] = encode_datapart({
        'profile_in': {'city': 'Paris', 'country_anchor': 'FR'},
        'query_params': {'areas_authoritative': True},
    })
    args = {'city': 'Rome', 'country_code': 'IT', 'zone': 'Centre',
            'areas': [{'query': 'Rome', 'kind': 'municipality', 'country': 'IT', 'evidence': 'Rome'}]}
    assert inject_profile_geo_context(SimpleNamespace(name='geocode_location'), args, ctx) is None
    assert args['city'] == 'Paris' and args['country_code'] == 'FR'
    assert 'zone' not in args


def test_explicit_city_boundary_replaces_province_in_actual_leaf_callback(monkeypatch):
    old = [{'query': 'Brescia', 'kind': 'administrative', 'country': 'IT', 'evidence': 'Brescia e provincia'}]
    new = [{'query': 'Brescia', 'kind': 'municipality', 'country': 'IT', 'evidence': 'Brescia',
            'boundary_evidence': 'solo entro i confini della città'}]
    provider = SimpleNamespace(geocode_candidates=lambda *a, **kw: [
        replace(candidate(), name='Brescia', country_code='IT', feature_type='place', mapbox_id='city-bs')
    ])
    monkeypatch.setattr('hotel_search_agent.geocode_tool.get_mapbox_client', lambda: provider)
    ctx = context({'city': 'provincia di Brescia', 'search_areas': old}, 'Brescia, solo entro i confini della città')
    result = inject_profile_geo_context(SimpleNamespace(name='geocode_location'), {'areas': new}, ctx)
    assert result['ok'] and result['search_areas'][0]['id'] == 'city-bs'
    assert result['profile_delta']['search_areas'] == new


def test_repeating_bounded_city_does_not_release_its_explicit_boundary():
    from b2c_common.search_areas import preserve_area_boundary
    old = [{'query': 'Bergamo', 'kind': 'municipality', 'country': 'IT', 'evidence': 'Bergamo',
            'boundary_evidence': 'solo nel comune'}]
    repeated = [{'query': 'Bergamo', 'kind': 'municipality', 'country': 'IT', 'evidence': 'Bergamo Italia'}]
    assert preserve_area_boundary(old, repeated) == old
    broadened = [{**repeated[0], 'kind': 'administrative', 'evidence': 'Bergamo e provincia'}]
    assert preserve_area_boundary(old, broadened) == broadened


@pytest.mark.parametrize('authoritative', [False, True])
def test_explicit_neighbourhood_uses_owned_landmark_contract_when_authoritative(authoritative):
    profile = {'city': 'Lyon' if authoritative else 'Paris', 'country_anchor': 'FR'}
    if authoritative:
        profile['zone'] = 'Part-Dieu'
    ctx = context(profile, 'Un hôtel à Lyon près de Part-Dieu')
    ctx.user_content.parts[-1] = encode_datapart({'profile_in': profile,
        'query_params': {'landmark_authoritative': authoritative}})
    args = {'zone': 'Part-Dieu', 'areas': [{'query': 'Lyon', 'kind': 'municipality',
                                           'country': 'FR', 'evidence': 'Lyon'}]}
    assert inject_profile_geo_context(SimpleNamespace(name='geocode_location'), args, ctx) is None
    assert args['city'] == 'Lyon' and args['zone'] == 'Part-Dieu'


@pytest.mark.parametrize('copied_zone', ['provincia di Brescia', None])
@pytest.mark.parametrize('profile_city', ['Brescia', 'provincia di Brescia'])
def test_generic_followup_keeps_province_despite_leaf_copied_zone(monkeypatch, copied_zone, profile_city):
    areas = [{'query': 'Brescia', 'kind': 'administrative', 'country': 'IT',
              'evidence': 'Brescia e provincia'}]
    provider = SimpleNamespace(geocode_candidates=lambda *a, **kw: [
        replace(candidate(), name='Brescia', country_code='IT', mapbox_id='province-bs')
    ])
    monkeypatch.setattr('hotel_search_agent.geocode_tool.get_mapbox_client', lambda: provider)
    args = {'city': 'Brescia', 'country_code': 'IT', 'raw_user_message': 'provincia di Brescia'}
    if copied_zone:
        args['zone'] = copied_zone
    ctx = context({'search_areas': areas, 'city': profile_city, 'country_anchor': 'IT'}, 'Tutte')
    result = inject_profile_geo_context(SimpleNamespace(name='geocode_location'), args, ctx)
    assert result and result['ok']
    assert result['profile_delta']['search_areas'] == areas


def test_explicit_neighborhood_can_refine_carried_province():
    areas = [{'query': 'Brescia', 'kind': 'administrative', 'country': 'IT',
              'evidence': 'Brescia e provincia'}]
    ctx = context({'search_areas': areas, 'city': 'Brescia', 'country_anchor': 'IT'},
                  'Vicino alla stazione di Brescia')
    args = {'city': 'Brescia', 'country_code': 'IT', 'zone': 'stazione di Brescia'}
    assert inject_profile_geo_context(SimpleNamespace(name='geocode_location'), args, ctx) is None
    assert args['zone'] == 'stazione di Brescia'


def test_narrowing_known_area_union_preserves_member_type():
    from b2c_common.search_areas import preserve_area_boundary
    update = [{**AREAS[1], 'kind': 'municipality', 'evidence': 'dans le 92'}]
    assert preserve_area_boundary(AREAS, update) == [AREAS[1]]
    bounded = [{**update[0], 'boundary_evidence': 'within the city limits'}]
    assert preserve_area_boundary(AREAS, bounded) == bounded


def test_owned_area_plan_precedes_a_premature_search(monkeypatch):
    from hotel_search_agent.response_bridge import prepare_owned_area_plan, enforce_resolved_search_origin
    monkeypatch.setattr('hotel_search_agent.geocode_tool.get_mapbox_client', client)
    ctx = context({'search_areas': AREAS, 'city': 'Yvelines / Hauts-de-Seine'})
    ctx.user_content.parts[-1] = encode_datapart({'profile_in': {'search_areas': AREAS},
                                                'query_params': {'areas_authoritative': True}})
    assert asyncio.run(prepare_owned_area_plan(ctx)) is None
    args = {'lat': 1, 'lon': 2}
    assert enforce_resolved_search_origin(SimpleNamespace(name='search_offers'), args, ctx) is None
    assert args['lat'] != 1 and args['lon'] != 2
    assert len(ctx.state[STATE_AREAS]) == 2
    assert ctx.state['temp:hotel_search_anchor']['type'] == 'area'


def test_carried_area_alone_does_not_preempt_fresh_leaf_destination(monkeypatch):
    from hotel_search_agent.response_bridge import prepare_owned_area_plan
    def unexpected():
        raise AssertionError('no pre-resolution without current authoritative intent')
    monkeypatch.setattr('hotel_search_agent.geocode_tool.get_mapbox_client', unexpected)
    ctx = context({'search_areas': AREAS}, 'Et à Lyon ?')
    assert asyncio.run(prepare_owned_area_plan(ctx)) is None
    assert not ctx.state.get(STATE_AREAS)


def test_failed_owned_area_plan_cannot_search_model_coordinates(monkeypatch):
    from hotel_search_agent.response_bridge import prepare_owned_area_plan, enforce_resolved_search_origin
    monkeypatch.setattr('hotel_search_agent.geocode_tool.get_mapbox_client',
                        lambda: SimpleNamespace(geocode_candidates=lambda *a, **kw: []))
    ctx = context()
    ctx.user_content.parts[-1] = encode_datapart({'profile_in': {'search_areas': AREAS},
                                                'query_params': {'areas_authoritative': True}})
    asyncio.run(prepare_owned_area_plan(ctx))
    result = enforce_resolved_search_origin(SimpleNamespace(name='search_offers'), {'lat': 1, 'lon': 2}, ctx)
    assert result['error'] == 'area_unresolved'
    assert not ctx.state.get(STATE_AREAS)


def test_strict_subarea_is_grounded_and_survives_parent_confirmation():
    from b2c_common.search_areas import preserve_area_boundary
    scope = {'query': 'Paris', 'kind': 'municipality', 'country': 'FR',
             'evidence': 'Paris', 'boundary_evidence': 'seulement', 'subarea': 'rive droite'}
    assert validate_areas([scope], 'Paris rive droite seulement') == [scope]
    assert validate_areas([scope], 'Paris seulement') is None
    repeated = [{k: v for k, v in scope.items() if k not in ('subarea', 'boundary_evidence')}]
    assert preserve_area_boundary([scope], repeated) == [scope]
    widened = [{**repeated[0], 'boundary_evidence': 'toute la ville'}]
    assert preserve_area_boundary([scope], widened) == widened


def _subarea_provider(*, child=True):
    parent = replace(candidate('Paris', '', 'paris'), feature_type='place', bbox=(2.22, 48.81, 2.42, 48.90))
    subset = replace(candidate('Le Marais', '', 'marais'), feature_type='neighborhood', parent_ids=('paris',), bbox=(2.35, 48.85, 2.37, 48.87))
    calls = []
    def geocode(query, **kwargs):
        calls.append(query)
        return [parent] if query == 'Paris' else [subset] if child else []
    return SimpleNamespace(geocode_candidates=geocode), calls


SUBAREA = {'query': 'Paris', 'kind': 'municipality', 'country': 'FR',
           'evidence': 'Paris', 'boundary_evidence': 'only', 'subarea': 'Le Marais'}


def test_unresolved_inner_area_never_becomes_verified_parent():
    provider, calls = _subarea_provider(child=False)
    result = resolve_areas([SUBAREA], provider)
    assert result['ok'] is False
    assert result['error'] == 'area_subarea_unresolved'
    assert result['diagnostics']['subarea'] == 'Le Marais'
    assert result['profile_delta']['search_areas'] == [SUBAREA]
    # The bounded child lookup fails immediately; no parent-city fallback can
    # turn that failure into compliant hotels.
    assert calls == ['Le Marais, Paris']


def test_partial_alternative_keeps_unresolved_inner_area_label():
    provider, _ = _subarea_provider(child=False)
    other = {k: v for k, v in SUBAREA.items() if k != 'subarea'}
    result = resolve_areas([SUBAREA, other], provider)
    assert result['ok']
    assert result['unresolved_areas'][0]['query'] == 'Paris — Le Marais'
    assert len(result['search_areas']) == 1


def test_area_membership_requires_parent_and_subarea_not_either(monkeypatch):
    provider, _ = _subarea_provider()
    resolved = resolve_areas([SUBAREA], provider)
    assert resolved['ok']
    area = resolved['search_areas'][0]
    assert area['label'] == 'Paris — Le Marais'
    assert area['radius_km'] < 5
    ctx = context()
    capture_after_tool(SimpleNamespace(name='geocode_location'), {}, ctx, resolved)
    ids = {1: {'paris'}, 2: {'marais'}, 3: {'paris', 'marais'}, 4: None}
    reverse = SimpleNamespace(containing_area_ids=lambda lat, lon: ids[int(lat)])
    monkeypatch.setattr('hotel_search_agent.geocode_tool.get_mapbox_client', lambda: reverse)
    async def run_async(*, args, tool_context):
        assert args['sortBy'] == 'distance'
        return {'structuredContent': {'results': [{'hotelId': i, 'lat': i, 'lon': 2} for i in ids]}}
    result = asyncio.run(search_areas_before_tool(SimpleNamespace(name='search_offers', run_async=run_async), {}, ctx))
    assert [h['hotelId'] for h in result['structuredContent']['results']] == [3]
    assert ctx.state[STATE_COVERAGE]['unverified'] == 1


def test_forward_subarea_parent_identity_is_not_its_own_id():
    payload = {'features': [{'geometry': {'coordinates': [2.1, 48.8]}, 'properties': {
        'name': 'Quarter', 'feature_type': 'neighborhood', 'mapbox_id': 'quarter',
        'context': {'neighborhood': {'mapbox_id': 'quarter'}, 'place': {'mapbox_id': 'parent'},
                    'country': {'country_code': 'FR', 'mapbox_id': 'country'}}}}]}
    parsed = MapboxClient._parse_candidates(payload)[0]
    assert 'parent' in parsed.parent_ids and 'quarter' not in parsed.parent_ids


def test_subarea_homonym_in_another_city_cannot_resolve_under_parent():
    provider, _ = _subarea_provider()
    original = provider.geocode_candidates
    def geocode(query, **kw):
        return [replace(c, parent_ids=('other-city',)) if c.feature_type == 'neighborhood' else c
                for c in original(query, **kw)]
    result = resolve_areas([SUBAREA], SimpleNamespace(geocode_candidates=geocode))
    assert result['error'] == 'area_subarea_unresolved'


def test_parallel_rejected_area_call_cannot_erase_applied_spa_on_next_turn(monkeypatch):
    async def scenario():
        # Actual v47 failure: triage rejected unknown massage, leaf emitted two
        # parallel calls: spa, then massage. Only the spa batch read inventory.
        from inspect import isawaitable
        from hotel_search_agent.agent import root_agent
        from hotel_search_agent.equipment_ids import enforce_equipment_filters
        from hotel_search_agent.response_bridge import STATE_APPLIED_AMENITIES_KEY

        ctx = context()
        ctx.invocation_id = 'area-parallel-regression'
        ctx.state[STATE_AREAS] = resolve_areas(AREAS[:1], client())['search_areas']
        gate = next(cb for cb in root_agent.before_tool_callback if cb.__module__.endswith('tool_budget_guard'))
        assert root_agent.before_tool_callback.index(gate) < root_agent.before_tool_callback.index(enforce_equipment_filters)
        released = asyncio.Event()
        dispatched = asyncio.Event()
        reads = []

        async def run_async(*, args, tool_context):
            reads.append(dict(args))
            dispatched.set()
            await released.wait()
            return {'structuredContent': {'results': [], 'total': 0}}

        monkeypatch.setattr('hotel_search_agent.geocode_tool.get_mapbox_client', lambda: SimpleNamespace())
        tool = SimpleNamespace(name='search_offers', run_async=run_async)

        async def dispatch(args):
            for callback in (gate, enforce_equipment_filters, search_areas_before_tool):
                response = callback(tool, args, ctx)
                if isawaitable(response):
                    response = await response
                if response is not None:
                    capture_after_tool(tool, args, ctx, response)
                    return response
            raise AssertionError('Area plan must own dispatch')

        first = asyncio.create_task(dispatch({'amenities': ['spa'], 'date': '2026-10-10'}))
        await dispatched.wait()
        second = await dispatch({'amenities': ['massage'], 'date': '2026-10-11'})
        released.set()
        await first
        assert second['ok'] is False and len(reads) == 1
        assert reads[0]['hotelEquipmentIds'] == [35]
        assert ctx.state[STATE_APPLIED_AMENITIES_KEY] == ['spa']
        payload = decode_datapart(emit_search_datapart(ctx).parts[-1])
        profile = SessionProfile()
        apply_profile_delta(profile, payload['profile_delta'], 'first search')
        # The same real envelope the next GPS/budget/time follow-up sends.
        following = context(SessionProfile.from_dict(profile.to_dict()).to_dict(), 'Near me')
        args = {}
        enforce_equipment_filters(tool, args, following)
        assert args['hotelEquipmentIds'] == [35]
    asyncio.run(scenario())


def test_refinement_keeps_both_children_and_requires_provider_parent_membership():
    from b2c_common.search_areas import preserve_area_boundary
    previous = [{'query': name, 'kind': 'municipality', 'country': 'FR', 'evidence': name}
                for name in ['Le Marais', 'Montmartre']]
    parent = [{'query': 'Paris', 'kind': 'municipality', 'country': 'FR', 'evidence': 'Paris'}]
    requests = preserve_area_boundary(previous, parent, parent_refinement=True)
    city = replace(candidate('Paris', '', 'paris'), feature_type='place', bbox=(2.22, 48.81, 2.42, 48.90))
    children = {name: replace(candidate(name, '', name), feature_type='neighborhood',
                parent_ids=('paris',), bbox=(2.35, 48.85, 2.37, 48.87)) for name in ['Le Marais', 'Montmartre']}
    def geocode(query, **kwargs):
        return [city] if query == 'Paris' else [children[query.split(',')[0]]]
    provider = SimpleNamespace(geocode_candidates=geocode)
    result = resolve_areas(requests, provider)
    assert result['ok'] and len(result['search_areas']) == 2
    assert {a['id'] for a in result['search_areas']} == set(children)
    assert all(a['required_parent_id'] == 'paris' for a in result['search_areas'])
    children['Montmartre'] = replace(children['Montmartre'], parent_ids=('another-city',))
    result = resolve_areas(requests, provider)
    assert len(result['search_areas']) == 1 and result['unresolved_areas']
    assert result['search_areas'][0]['id'] == 'Le Marais'  # Never substitute Paris.


@pytest.mark.parametrize('update', [
    [{'query': 'London', 'kind': 'municipality', 'country': 'GB', 'evidence': 'London'}],
    [{'query': 'Le Marais', 'kind': 'municipality', 'country': 'FR', 'evidence': 'Le Marais'}],
])
def test_cross_country_or_selected_alternative_does_not_become_a_parent(update):
    from b2c_common.search_areas import preserve_area_boundary
    previous = [{'query': name, 'kind': 'municipality', 'country': 'FR', 'evidence': name}
                for name in ['Le Marais', 'Montmartre']]
    assert preserve_area_boundary(previous, update, parent_refinement=True) == update
