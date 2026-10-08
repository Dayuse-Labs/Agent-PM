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


def candidate(name="Yvelines", code="78", ident="area78", **kwargs):
    return GeocodeCandidate(48.8, 1.8, name, name, "France", "region", "FR", name,
                            (1.44, 48.43, 2.23, 49.09), 0, ident, code, **kwargs)


def client():
    return SimpleNamespace(geocode_candidates=lambda query, **kw: [candidate() if query == "Yvelines" else candidate("Hauts-de-Seine", "92", "area92")])


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


@pytest.mark.parametrize("value", [None, [], AREAS * 2, [{**AREAS[0], "latitude": "48"}],
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
    assert item['properties']['kind']['enum'] == ['administrative', 'municipality']


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
