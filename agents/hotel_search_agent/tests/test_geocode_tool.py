"""geocode_location — composition of the 3 geo guards + Mapbox, tested with a
fake client (no network): degrade honestly on every rejection path, never
raise.
"""
from __future__ import annotations

import httpx
import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types as genai_types

from hotel_search_agent import geocode_tool
from hotel_search_agent.geocode_tool import geocode_location, inject_profile_geo_context
from hotel_search_agent.mapbox_client import GeocodeCandidate, GeocodeResult, MapboxClient


class FakeMapboxClient:
    """Serves ONE candidate (or none) so the single-result guard behaviours
    (echo, ZIP scoping, generic demotion, state anchoring) can be asserted
    without a network call. A lone candidate always wins the resolver
    (len==1 → select), so the downstream echo check runs exactly as before."""

    def __init__(self, result: GeocodeResult | None):
        self.result = result
        self.calls: list[tuple] = []

    def geocode(self, query, *, country=None, **kwargs):
        self.calls.append((query, country))
        return self.result

    def geocode_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, country))
        if self.result is None:
            return []
        r = self.result
        return [
            GeocodeCandidate(
                latitude=r.latitude,
                longitude=r.longitude,
                name=r.place_name.split(",")[0],
                place_name=r.place_name,
                place_formatted=r.place_name,
                feature_type="place",
                country_code=r.country_code,
                region=r.region,
                bbox=None,
                rank=0,
            )
        ]


class _NoSearchBox:
    """Tier-2 disabled offline: a miss degrades honestly instead of hitting the
    network. Tests that exercise the Search-Box fallback patch this explicitly."""

    def forward(self, *args, **kwargs):
        return None


@pytest.fixture(autouse=True)
def _no_network_searchbox(monkeypatch):
    monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _NoSearchBox())


def _patch_client(monkeypatch, result: GeocodeResult | None) -> FakeMapboxClient:
    fake = FakeMapboxClient(result)
    monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: fake)
    return fake


FLORENCE_KY = GeocodeResult(
    latitude=38.9989,
    longitude=-84.6266,
    place_name="Florence, Kentucky, United States",
    country_code="US",
    region="KY",
)


class TestSuccess:
    def test_resolves_city_to_coordinates(self, monkeypatch):
        fake = _patch_client(monkeypatch, FLORENCE_KY)

        result = geocode_location(city="Florence", raw_user_message="florence kentucky")

        assert result["ok"] is True
        assert result["latitude"] == 38.9989
        assert result["longitude"] == -84.6266
        assert result["resolved_place"] == "Florence, Kentucky, United States"
        assert result["country_code"] == "US"
        assert fake.calls == [("Florence, Kentucky", None)]

    def test_profile_delta_anchors_state_context(self, monkeypatch):
        _patch_client(monkeypatch, FLORENCE_KY)

        result = geocode_location(city="Florence", raw_user_message="florence kentucky")

        assert result["profile_delta"]["last_state_context"] == "KY"
        assert result["profile_delta"]["last_city"] == "Florence"

    def test_zone_included_in_geocode_query(self, monkeypatch):
        fake = _patch_client(
            monkeypatch,
            GeocodeResult(
                latitude=25.7898,
                longitude=-80.1366,
                place_name="Hollywood, Florida, United States",
                country_code="US",
                region="FL",
            ),
        )

        result = geocode_location(city="Miami", zone="Hollywood")

        assert result["ok"] is True
        assert fake.calls == [("Hollywood, Miami", None)]


class TestGenericCityDemotion:
    def test_bare_generic_city_never_reaches_the_geocoder(self, monkeypatch):
        fake = _patch_client(monkeypatch, FLORENCE_KY)

        result = geocode_location(city="airport")

        assert result == {
            "ok": False,
            "error": "no_geocodable_location",
            "diagnostics": {"reason": "generic_location_only", "zone_hint": "airport"},
        }
        assert fake.calls == []

    def test_missing_city_and_metro_is_a_clean_diagnostic(self, monkeypatch):
        fake = _patch_client(monkeypatch, FLORENCE_KY)

        result = geocode_location(city="")

        assert result["ok"] is False
        assert result["error"] == "no_geocodable_location"
        assert result["diagnostics"]["reason"] == "missing_city"
        assert fake.calls == []


class TestEchoBackGuard:
    def test_rejects_mismatched_geocode_result(self, monkeypatch):
        # Mapbox limit=1 fuzz: asked for Budapest, got Atlanta back.
        _patch_client(
            monkeypatch,
            GeocodeResult(
                latitude=33.7490,
                longitude=-84.3880,
                place_name="Atlanta, Georgia, United States",
                country_code="US",
                region="GA",
            ),
        )

        result = geocode_location(city="Budapest", zone="Keleti train station")

        assert result["ok"] is False
        assert result["error"] == "geocode_echo_mismatch"
        assert result["diagnostics"]["resolved_place"] == "Atlanta, Georgia, United States"

    def test_rejects_wrong_state_for_florence(self, monkeypatch):
        _patch_client(
            monkeypatch,
            GeocodeResult(
                latitude=43.7696,
                longitude=11.2558,
                place_name="Florence, Tuscany, Italy",
                country_code="IT",
                region="Tuscany",
            ),
        )

        result = geocode_location(city="Florence", raw_user_message="florence kentucky")

        assert result["ok"] is False
        assert result["error"] == "geocode_echo_mismatch"


class TestGeocoderDegradation:
    def test_no_result_degrades_honestly(self, monkeypatch):
        _patch_client(monkeypatch, None)

        result = geocode_location(city="Nowhereville")

        assert result == {
            "ok": False,
            "error": "geocode_unavailable",
            "diagnostics": {"query": "Nowhereville"},
        }


class TestUsZipCountryScoping:
    """Prod bug: a 5-digit US ZIP ("near 11580") geocoded worldwide when the
    model didn't also extract country_code. `select_us_postal_anchor`
    (geo_guards.py, ported S4) existed but was never wired into a real
    request — this locks the fix at the FakeMapboxClient level (mirrors the
    existing suite's convention) and once more against the real MapboxClient
    HTTP layer (httpx.MockTransport) so the actual Mapbox URL is asserted.
    """

    def test_zip_anchor_forces_country_code_on_the_fake_client(self, monkeypatch):
        fake = _patch_client(monkeypatch, FLORENCE_KY)

        geocode_location(city="11580", raw_user_message="Allows cats. Near 11580")

        assert fake.calls == [("11580", "US")]

    def test_no_zip_and_no_country_signal_stays_unscoped(self, monkeypatch):
        fake = _patch_client(monkeypatch, FLORENCE_KY)

        geocode_location(city="Florence", raw_user_message="florence kentucky")

        assert fake.calls == [("Florence, Kentucky", None)]

    def test_explicit_country_code_wins_over_a_stray_five_digit_number(self, monkeypatch):
        fake = _patch_client(monkeypatch, FLORENCE_KY)

        geocode_location(city="Paris", raw_user_message="paris 75015", country_code="FR")

        assert fake.calls == [("Paris", "FR")]

    def test_zip_anchor_scopes_the_real_mapbox_request_url(self, monkeypatch):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(
                200,
                json={
                    "features": [
                        {
                            "geometry": {"coordinates": [-73.6501, 40.6187]},
                            "properties": {
                                "full_address": "11580, Island Park, New York, United States",
                                "context": {
                                    "country": {"country_code": "us"},
                                    "region": {"region_code": "NY", "name": "New York"},
                                },
                            },
                        }
                    ]
                },
            )

        real_client = MapboxClient(
            "test-token", client=httpx.Client(transport=httpx.MockTransport(handler))
        )
        monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: real_client)

        result = geocode_location(city="11580", raw_user_message="Allows cats. Near 11580")

        assert result["ok"] is True
        assert result["country_code"] == "US"
        assert seen["params"]["country"] == "us"

    def test_no_zip_anchor_leaves_the_real_mapbox_request_url_unscoped(self, monkeypatch):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json={"features": []})

        real_client = MapboxClient(
            "test-token", client=httpx.Client(transport=httpx.MockTransport(handler))
        )
        monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: real_client)

        geocode_location(city="Florence", raw_user_message="florence kentucky")

        assert "country" not in seen["params"]


# --- multi-candidate resolver / clarify / Search-Box tier-2 (S-G3) --------------------------
def _c(name, cc, region, *, ftype="place", rank=0, lat=0.0, lon=0.0):
    return GeocodeCandidate(
        latitude=lat,
        longitude=lon,
        name=name,
        place_name=f"{name}, {region}, {cc}",
        place_formatted=f"{region}, {cc}",
        feature_type=ftype,
        country_code=cc,
        region=region,
        bbox=None,
        rank=rank,
    )


class _MultiClient:
    def __init__(self, candidates):
        self.candidates = candidates
        self.calls: list[tuple] = []
        self.langs: list = []
        self.proximities: list = []

    def geocode_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, country))
        self.langs.append(language)
        self.proximities.append(proximity)
        return list(self.candidates)


class _FakeSearchBox:
    def __init__(self, result):
        self.result = result
        self.calls: list[tuple] = []

    def forward(self, query, *, country=None, language=None, **kwargs):
        self.calls.append((query, country))
        return self.result


class _FakeInventory:
    def __init__(self, by_lat):
        self.by_lat = by_lat

    def count_near(self, lat, lon, *, radius_km=25.0):
        return self.by_lat.get(round(lat, 4), 0)


def _patch_multi(monkeypatch, candidates, *, inventory=None):
    client = _MultiClient(candidates)
    monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: client)
    inv = _FakeInventory(inventory or {})
    monkeypatch.setattr(geocode_tool, "get_inventory", lambda: inv)
    return client


class TestMultiCandidateResolution:
    def test_inventory_winner_is_selected_across_candidates(self, monkeypatch):
        milan = _c("Milano", "IT", "Milan", lat=45.46, rank=0)
        texas = _c("Milano", "US", "Texas", lat=30.71, rank=1)
        _patch_multi(monkeypatch, [milan, texas], inventory={45.46: 40, 30.71: 0})

        result = geocode_location(city="Milano", raw_user_message="hotel a Milano")

        assert result["ok"] is True
        assert result["resolved_place"] == "Milano, Milan, IT"
        assert result["country_code"] == "IT"
        assert result["distance_origin_type"] == "city_centroid"

    def test_ambiguous_homonym_returns_clarify_not_a_guess(self, monkeypatch):
        bc = _c("Victoria", "CA", "British Columbia", lat=48.43, rank=0)
        tx = _c("Victoria", "US", "Texas", lat=28.80, rank=1)
        _patch_multi(monkeypatch, [bc, tx], inventory={48.43: 20, 28.80: 15})

        result = geocode_location(city="Victoria", raw_user_message="hotel in Victoria")

        assert result["ok"] is False
        assert result["error"] == "geocode_ambiguous"
        assert "Victoria" in result["diagnostics"]["question"]
        countries = {o["country_code"] for o in result["diagnostics"]["options"]}
        assert {"CA", "US"} <= countries

    def test_locale_is_passed_to_mapbox_as_language(self, monkeypatch):
        lisbon = _c("Lisbon", "PT", "Lisboa", lat=38.72, rank=0)
        client = _patch_multi(monkeypatch, [lisbon], inventory={38.72: 26})

        geocode_location(city="Lisboa", raw_user_message="hotel em Lisboa", locale="pt")

        assert client.langs == ["pt"]

    def test_language_hint_fills_mapbox_language_when_no_locale(self, monkeypatch):
        # S-G10 (La Défense→AE root cause): Mapbox's candidate LIST changes with
        # `language` — the bare "La Défense" query only returns the Puteaux-FR
        # candidates when a language is sent. The triage language is the fallback.
        paris = _c("Paris", "FR", "Île-de-France", lat=48.85, rank=0)
        client = _patch_multi(monkeypatch, [paris], inventory={48.85: 40})

        geocode_location(city="Paris", raw_user_message="hôtel à Paris", language_hint="fr")

        assert client.langs == ["fr"]

    def test_real_locale_wins_over_language_hint(self, monkeypatch):
        lisbon = _c("Lisbon", "PT", "Lisboa", lat=38.72, rank=0)
        client = _patch_multi(monkeypatch, [lisbon], inventory={38.72: 26})

        geocode_location(
            city="Lisboa", raw_user_message="hoteis", locale="pt-PT", language_hint="fr"
        )

        assert client.langs == ["pt"]

    def test_language_hint_never_feeds_the_country_prior(self, monkeypatch):
        # S-G7 pitfall, locked: a triage fr/en guess must never act as the
        # _W_LOCALE country boost. Two same-tier `place` candidates, US at
        # Mapbox rank 0 — if "fr" wrongly fed the prior, the FR candidate
        # (+1.0) would become the top (and lead the clarify options).
        us = _c("Clermont", "US", "Florida", lat=28.55, rank=0)
        fr = _c("Clermont", "FR", "Auvergne", lat=45.78, rank=1)
        _patch_multi(monkeypatch, [us, fr], inventory={28.55: 20, 45.78: 20})

        result = geocode_location(
            city="Clermont", raw_user_message="hotel in Clermont", language_hint="fr"
        )

        assert result["error"] == "geocode_ambiguous"
        assert result["diagnostics"]["options"][0]["country_code"] == "US"


class TestGpsOnlyResolution:
    def test_near_me_with_gps_anchor_resolves_to_the_fix(self, monkeypatch):
        # S-G10 (D1 follow-up): a GPS-only request ("near me", no city/zone
        # anywhere) resolves to the device fix itself — before this the leaf
        # could never search at all for the widget's real GPS-only requests.
        _patch_multi(monkeypatch, [], inventory={})

        result = geocode_location(
            city="", raw_user_message="a room in the daytime near me",
            proximity_lat=48.9385, proximity_lon=2.4906,
        )

        assert result["ok"] is True
        assert result["latitude"] == 48.9385
        assert result["longitude"] == 2.4906
        assert result["distance_origin_type"] == "gps"

    def test_named_landmark_is_never_replaced_by_the_gps_fix(self, monkeypatch):
        # Gate 3: "near the airport" + GPS must NOT silently search the user's
        # own location — the zone-without-city error stands.
        _patch_multi(monkeypatch, [], inventory={})
        box = _FakeSearchBox(None)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)

        result = geocode_location(
            city="", zone="the airport", raw_user_message="near the airport",
            proximity_lat=48.9385, proximity_lon=2.4906,
        )

        assert result["ok"] is False
        assert result["error"] == "no_geocodable_location"

    def test_near_me_without_gps_still_asks_for_a_destination(self, monkeypatch):
        _patch_multi(monkeypatch, [], inventory={})

        result = geocode_location(city="", raw_user_message="near me")

        assert result["ok"] is False
        assert result["error"] == "no_geocodable_location"


class TestSearchBoxTier2:
    def test_zone_miss_falls_back_to_search_box(self, monkeypatch):
        # v6 returns only junk that fails the echo check; a zone was named.
        junk = _c("Al Ain", "AE", "Abu Dhabi", ftype="neighborhood", lat=24.2, rank=0)
        _patch_multi(monkeypatch, [junk], inventory={24.2: 0})
        poi = GeocodeResult(
            latitude=48.8918,
            longitude=2.2387,
            place_name="La Défense, 92800 Puteaux, France",
            country_code="FR",
            region="Île-de-France",
        )
        box = _FakeSearchBox(poi)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)

        result = geocode_location(city="Paris", zone="La Défense", raw_user_message="hotel la défense")

        assert result["ok"] is True
        assert result["resolved_place"] == "La Défense, 92800 Puteaux, France"
        assert result["distance_origin_type"] == "poi"
        assert box.calls  # the fallback was actually invoked

    def test_no_zone_never_calls_search_box(self, monkeypatch):
        junk = _c("Al Ain", "AE", "Abu Dhabi", ftype="neighborhood", lat=24.2, rank=0)
        _patch_multi(monkeypatch, [junk], inventory={24.2: 0})
        box = _FakeSearchBox(None)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)

        result = geocode_location(city="Budapestttt", raw_user_message="hotel budapestttt")

        assert result["ok"] is False
        assert result["error"] == "geocode_echo_mismatch"
        assert box.calls == []  # never invoked without a zone/landmark

    def test_clarify_with_a_zone_tries_search_box_before_asking(self, monkeypatch):
        # S-G10: a named landmark can make v6's whole list fuzzy homonyms in a
        # near-tie (clarify) — the echo-validated POI tier must win over asking
        # the user to pick among fuzz ("La Defensa (Colombia) or ...?").
        co = _c("La Defensa", "CO", "Vichada", ftype="locality", lat=5.58, rank=0)
        ae = _c("Defense", "AE", "Abu Dhabi", ftype="neighborhood", lat=23.64, rank=2)
        _patch_multi(monkeypatch, [co, ae], inventory={5.58: 0, 23.64: 1})
        poi = GeocodeResult(
            latitude=48.8918,
            longitude=2.2387,
            place_name="La Défense, 92800 Puteaux, France",
            country_code="FR",
            region="Île-de-France",
        )
        box = _FakeSearchBox(poi)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)

        result = geocode_location(city="Paris", zone="La Défense", raw_user_message="hotel la défense")

        assert result["ok"] is True
        assert result["country_code"] == "FR"
        assert result["distance_origin_type"] == "poi"

    def test_clarify_surfaces_when_search_box_misses_too(self, monkeypatch):
        co = _c("La Defensa", "CO", "Vichada", ftype="locality", lat=5.58, rank=0)
        ae = _c("Defense", "AE", "Abu Dhabi", ftype="neighborhood", lat=23.64, rank=2)
        _patch_multi(monkeypatch, [co, ae], inventory={5.58: 0, 23.64: 1})
        box = _FakeSearchBox(None)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)

        result = geocode_location(city="Paris", zone="La Défense", raw_user_message="hotel la défense")

        assert result["ok"] is False
        assert result["error"] == "geocode_ambiguous"
        assert box.calls  # tier 2 was tried first


# --- zone/metro in profile_delta (S-G5: previously never persisted) --------------------------
class TestZoneMetroDelta:
    def test_zone_included_in_delta_when_resolved(self, monkeypatch):
        _patch_multi(
            monkeypatch,
            [_c("Hollywood", "US", "Florida", lat=25.79)],
            inventory={25.79: 5},
        )

        result = geocode_location(city="Miami", zone="Hollywood")

        assert result["profile_delta"]["zone"] == "Hollywood"

    def test_metro_included_in_delta_when_resolved(self, monkeypatch):
        _patch_multi(monkeypatch, [_c("Paris", "FR", "Île-de-France", lat=48.85)], inventory={48.85: 5})

        result = geocode_location(city="Paris", metro="Île-de-France")

        assert result["profile_delta"]["metro"] == "Île-de-France"

    def test_zone_absent_from_delta_when_not_given(self, monkeypatch):
        _patch_multi(monkeypatch, [_c("Milano", "IT", "Milan", lat=45.46)], inventory={45.46: 5})

        result = geocode_location(city="Milano")

        assert "zone" not in result["profile_delta"]
        assert "metro" not in result["profile_delta"]

    def test_zone_included_via_search_box_tier2(self, monkeypatch):
        junk = _c("Al Ain", "AE", "Abu Dhabi", ftype="neighborhood", lat=24.2, rank=0)
        _patch_multi(monkeypatch, [junk], inventory={24.2: 0})
        poi = GeocodeResult(
            latitude=48.8918, longitude=2.2387,
            place_name="La Défense, 92800 Puteaux, France",
            country_code="FR", region="Île-de-France",
        )
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _FakeSearchBox(poi))

        result = geocode_location(city="Paris", zone="La Défense", raw_user_message="hotel la défense")

        assert result["ok"] is True
        assert result["profile_delta"]["zone"] == "La Défense"


# --- GPS proximity wiring (S-G5) --------------------------------------------------------------
class TestProximityWiring:
    def test_lat_and_lon_reach_mapbox_as_lon_lat_string_and_resolver_as_tuple(self, monkeypatch):
        milan = _c("Milano", "IT", "Milan", lat=45.46, rank=0)
        client = _patch_multi(monkeypatch, [milan], inventory={45.46: 10})

        captured: dict = {}
        real_resolve = geocode_tool.geo_resolver.resolve

        def spy_resolve(candidates, **kwargs):
            captured["proximity"] = kwargs.get("proximity")
            return real_resolve(candidates, **kwargs)

        monkeypatch.setattr(geocode_tool.geo_resolver, "resolve", spy_resolve)

        geocode_location(city="Milano", proximity_lat=45.0, proximity_lon=9.0)

        assert client.proximities == ["9.0,45.0"]
        assert captured["proximity"] == (45.0, 9.0)

    def test_a_lone_lat_or_lon_is_ignored(self, monkeypatch):
        milan = _c("Milano", "IT", "Milan", lat=45.46, rank=0)
        client = _patch_multi(monkeypatch, [milan], inventory={45.46: 10})

        geocode_location(city="Milano", proximity_lat=45.0, proximity_lon=None)

        assert client.proximities == [None]

    def test_no_proximity_by_default(self, monkeypatch):
        milan = _c("Milano", "IT", "Milan", lat=45.46, rank=0)
        client = _patch_multi(monkeypatch, [milan], inventory={45.46: 10})

        geocode_location(city="Milano")

        assert client.proximities == [None]


# --- inject_profile_geo_context (before_tool_callback, P0 #4 fix / S-G5) ----------------------
class _Ctx:
    def __init__(self, state=None, user_content=None):
        self.state = state if state is not None else {}
        self.user_content = user_content


class _Tool:
    def __init__(self, name):
        self.name = name


def _user_content_with_profile_in(profile_in: dict) -> genai_types.Content:
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in})
    )
    return genai_types.Content(
        role="user",
        parts=[genai_types.Part(text="autres options"), convert_a2a_part_to_genai_part(datapart)],
    )


class TestInjectProfileGeoContext:
    def test_ignores_other_tools(self):
        args = {"lat": 1}
        ctx = _Ctx(user_content=_user_content_with_profile_in({"city": "Miami"}))
        assert inject_profile_geo_context(_Tool("search_offers"), args, ctx) is None
        assert args == {"lat": 1}

    def test_empty_profile_leaves_args_untouched(self):
        args = {"city": "Paris"}
        assert inject_profile_geo_context(_Tool("geocode_location"), args, _Ctx()) is None
        assert args == {"city": "Paris"}

    def test_fresh_city_wins_over_profile(self):
        args = {"city": "Lisbon"}
        ctx = _Ctx(user_content=_user_content_with_profile_in({"city": "Paris"}))
        inject_profile_geo_context(_Tool("geocode_location"), args, ctx)
        assert args["city"] == "Lisbon"

    def test_blank_city_filled_from_profile(self):
        for blank_city in ("", "   "):
            args = {"city": blank_city}
            ctx = _Ctx(user_content=_user_content_with_profile_in({"city": "Paris"}))
            inject_profile_geo_context(_Tool("geocode_location"), args, ctx)
            assert args["city"] == "Paris"

    def test_zone_metro_country_code_filled_when_blank(self):
        args = {"city": "Paris"}
        ctx = _Ctx(
            user_content=_user_content_with_profile_in(
                {"zone": "La Défense", "metro": "Île-de-France", "country_anchor": "FR"}
            )
        )
        inject_profile_geo_context(_Tool("geocode_location"), args, ctx)
        assert args["zone"] == "La Défense"
        assert args["metro"] == "Île-de-France"
        assert args["country_code"] == "FR"

    def test_zone_metro_country_code_not_overwritten_when_fresh(self):
        args = {"city": "Paris", "zone": "Montmartre", "country_code": "FR"}
        ctx = _Ctx(
            user_content=_user_content_with_profile_in(
                {"zone": "La Défense", "country_anchor": "US"}
            )
        )
        inject_profile_geo_context(_Tool("geocode_location"), args, ctx)
        assert args["zone"] == "Montmartre"
        assert args["country_code"] == "FR"

    def test_profile_state_context_and_location_hint_always_profile_sourced(self):
        # Pure profile lookups by definition — set regardless of what the model
        # itself extracted for `city` THIS turn.
        args = {"city": "Lisbon", "profile_state_context": "should be overwritten"}
        ctx = _Ctx(
            user_content=_user_content_with_profile_in({"city": "Paris", "state_anchor": "KY"})
        )
        inject_profile_geo_context(_Tool("geocode_location"), args, ctx)
        assert args["profile_state_context"] == "KY"
        assert args["profile_location_hint"] == "Paris"

    def test_no_state_anchor_leaves_profile_state_context_unset(self):
        args = {"city": "Paris"}
        ctx = _Ctx(user_content=_user_content_with_profile_in({"city": "Paris"}))
        inject_profile_geo_context(_Tool("geocode_location"), args, ctx)
        assert "profile_state_context" not in args

    def test_search_anchor_becomes_proximity_lat_lon(self):
        args = {"city": "Paris"}
        ctx = _Ctx(
            user_content=_user_content_with_profile_in(
                {"search_anchor": {"type": "gps", "lat": 48.85, "lon": 2.35, "label": "me"}}
            )
        )
        inject_profile_geo_context(_Tool("geocode_location"), args, ctx)
        assert args["proximity_lat"] == 48.85
        assert args["proximity_lon"] == 2.35

    def test_incomplete_search_anchor_is_ignored(self):
        args = {"city": "Paris"}
        ctx = _Ctx(
            user_content=_user_content_with_profile_in({"search_anchor": {"type": "gps", "lat": 48.85}})
        )
        inject_profile_geo_context(_Tool("geocode_location"), args, ctx)
        assert "proximity_lat" not in args
        assert "proximity_lon" not in args

    def test_locale_always_profile_sourced(self):
        # S-G7: PURE profile lookup (profile_in.locale, the client's real
        # native-context tag) — always set, whatever the model itself passed
        # (the model has no reliable way to know the client's UI locale).
        args = {"city": "Lisboa", "locale": "should be overwritten"}
        ctx = _Ctx(user_content=_user_content_with_profile_in({"locale": "pt-PT"}))
        inject_profile_geo_context(_Tool("geocode_location"), args, ctx)
        assert args["locale"] == "pt-PT"

    def test_no_locale_leaves_locale_unset(self):
        args = {"city": "Paris"}
        ctx = _Ctx(user_content=_user_content_with_profile_in({"city": "Paris"}))
        inject_profile_geo_context(_Tool("geocode_location"), args, ctx)
        assert "locale" not in args

    def test_language_hint_always_profile_sourced(self):
        # S-G10: same category as locale — the triage conversation language
        # (profile_in.language) is a pure profile lookup, injected so Mapbox's
        # `language` param has a fallback when the client sent no locale.
        args = {"city": "La Défense", "language_hint": "should be overwritten"}
        ctx = _Ctx(user_content=_user_content_with_profile_in({"language": "fr"}))
        inject_profile_geo_context(_Tool("geocode_location"), args, ctx)
        assert args["language_hint"] == "fr"
