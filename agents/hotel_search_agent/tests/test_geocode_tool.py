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


def _as_candidate(result: GeocodeResult, *, feature_type: str = "poi", rank: int = 0) -> GeocodeCandidate:
    """A Search-Box result in the candidate shape the tier now consumes. Tier 2
    switched from Mapbox's `limit=1` top pick to the full candidate list ranked
    by `geo_resolver.rank_landmark` (2026-08-26: that top-1 is biased by the
    caller's egress IP), so the fakes hand back candidates."""
    return GeocodeCandidate(
        latitude=result.latitude,
        longitude=result.longitude,
        name=result.place_name.split(",")[0],
        place_name=result.place_name,
        place_formatted=result.place_name,
        feature_type=feature_type,
        country_code=result.country_code,
        region=result.region,
        bbox=None,
        rank=rank,
    )


class _NoSearchBox:
    """Tier-2 disabled offline: a miss degrades honestly instead of hitting the
    network. Tests that exercise the Search-Box fallback patch this explicitly."""

    def forward(self, *args, **kwargs):
        return None

    def forward_candidates(self, *args, **kwargs):
        return []


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
            # OBS3 (2026-08-26): the demotion guard now REPORTS itself, so the
            # concierge can score it. Before this the 3 geo guards were wired
            # nowhere and their Langfuse series sat at 0.0 forever, which is
            # what made "guard_generic_location_demotion = false" on the Toulon
            # trace look like a structural false negative rather than an
            # unwired score.
            "guards_fired": ["generic_location_demotion"],
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
        # Zero v6 candidates now also tries the Search-Box tier (S-G11) — a
        # miss there too degrades with "no_match" (the geocoder answered,
        # nothing matched — never dressed up as a service outage).
        _patch_client(monkeypatch, None)
        box = _FakeSearchBox(None)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)

        result = geocode_location(city="Nowhereville")

        assert result == {
            "ok": False,
            "error": "geocode_no_match",
            "diagnostics": {"query": "Nowhereville"},
        }
        assert box.calls  # the POI tier was tried before giving up


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
        # P0-2: the tier-2 SCOPE (country + proximity) is the whole point of the
        # M3 fix, so the fake has to record it — before this it swallowed both
        # in **kwargs and the gap was untestable in either direction.
        self.countries: list = []
        self.proximities: list = []
        self.langs: list = []

    def forward(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, country))
        self.countries.append(country)
        self.proximities.append(proximity)
        self.langs.append(language)
        return self.result

    def forward_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, country))
        self.countries.append(country)
        self.proximities.append(proximity)
        self.langs.append(language)
        return [] if self.result is None else [_as_candidate(self.result)]


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

    def test_bare_poi_destination_with_zero_candidates_falls_back_to_search_box(self, monkeypatch):
        # S-G11 "Layover in JFK": an airport used AS the destination is a POI —
        # v6's city feature types return ZERO candidates for it, and the old
        # zone-only trigger made the Search-Box tier unreachable (the user got
        # a bogus "geolocation service unavailable"). Zero candidates → try
        # Search Box with the city string itself.
        _patch_multi(monkeypatch, [], inventory={})
        poi = GeocodeResult(
            latitude=40.6413,
            longitude=-73.7781,
            place_name="John F. Kennedy International Airport, Jamaica, New York 11430, United States",
            country_code="US",
            region="New York",
        )
        box = _FakeSearchBox(poi)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)

        result = geocode_location(city="JFK", raw_user_message="Layover in JFK")

        assert result["ok"] is True
        assert result["distance_origin_type"] == "poi"
        assert result["country_code"] == "US"
        assert box.calls == [("JFK", None)]

    def test_bare_city_miss_with_candidates_still_never_calls_search_box(self, monkeypatch):
        # The SKU-cost rule is unchanged: when v6 HAS candidates (they just
        # fail the echo), a bare-city request must not hit Search Box.
        junk = _c("Al Ain", "AE", "Abu Dhabi", ftype="neighborhood", lat=24.2, rank=0)
        _patch_multi(monkeypatch, [junk], inventory={24.2: 0})
        box = _FakeSearchBox(None)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)

        result = geocode_location(city="Budapestttt", raw_user_message="hotel budapestttt")

        assert result["error"] == "geocode_echo_mismatch"
        assert box.calls == []

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


_CHAMPS = GeocodeResult(
    latitude=48.8698,
    longitude=2.3078,
    place_name="Avenue des Champs-Élysées, 75008 Paris, France",
    country_code="FR",
    region="Île-de-France",
)


class TestZoneOnlyLandmarkReachesSearchBox:
    """P0-2 fix 1 (audit §1 M2). A named landmark with no city used to return
    `no_geocodable_location` BEFORE the Search-Box tier ran, so whether it
    resolved depended on which field the model put the string in."""

    def _box(self, monkeypatch, result):
        box = _FakeSearchBox(result)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)
        return box

    def test_bare_landmark_with_no_city_resolves_once_an_anchor_exists(self, monkeypatch):
        _patch_multi(monkeypatch, [], inventory={})
        box = self._box(monkeypatch, _CHAMPS)

        result = geocode_location(
            city="", zone="champs élysées",
            raw_user_message="je cherche un hôtel autour des champs élysées",
            locale="fr-FR", country_guess="FR",
            # 2026-08-26: unanchored, this shape now asks which city (see
            # TestUnanchoredZoneAsksForTheCity). The P0-2 win fenced here is that
            # the landmark REACHES tier 2 instead of dying before it ran.
            proximity_lat=48.87, proximity_lon=2.31,
        )

        assert result["ok"] is True
        assert result["latitude"] == 48.8698
        assert result["distance_origin_type"] == "poi"
        assert box.calls[0][0] == "champs élysées"

    def test_a_generic_zone_is_still_refused_not_looked_up(self, monkeypatch):
        # "the airport" is not a landmark: looking it up worldwide would return
        # some airport on another continent. Deterministic discriminator.
        _patch_multi(monkeypatch, [], inventory={})
        box = self._box(monkeypatch, _CHAMPS)

        result = geocode_location(
            city="", zone="the airport", raw_user_message="near the airport"
        )

        assert result["ok"] is False
        assert result["error"] == "no_geocodable_location"
        assert box.calls == []  # never consulted

    def test_gate_3_still_holds_a_landmark_is_not_replaced_by_gps(self, monkeypatch):
        # The pinned invariant: with a GENERIC zone + GPS, the error stands and
        # the user's own fix is NOT silently substituted.
        _patch_multi(monkeypatch, [], inventory={})
        self._box(monkeypatch, None)

        result = geocode_location(
            city="", zone="the airport", raw_user_message="near the airport",
            proximity_lat=48.9385, proximity_lon=2.4906,
        )

        assert result["ok"] is False
        assert result["error"] == "no_geocodable_location"

    def test_a_landmark_that_search_box_misses_is_an_honest_failure(self, monkeypatch):
        _patch_multi(monkeypatch, [], inventory={})
        self._box(monkeypatch, None)

        result = geocode_location(
            city="", zone="zzz nonexistent landmark", raw_user_message="hotel there",
            proximity_lat=48.87, proximity_lon=2.31,
        )

        assert result["ok"] is False
        assert result["error"] == "no_geocodable_location"

    def test_an_echo_mismatch_is_not_accepted_even_scoped(self, monkeypatch):
        # M4 still guards: a POI whose NAME does not echo the request is refused.
        _patch_multi(monkeypatch, [], inventory={})
        elsewhere = GeocodeResult(
            latitude=5.35, longitude=-4.02,
            place_name="Hôtel Ivoire, Abidjan, Côte d'Ivoire",
            country_code="CI", region="Abidjan",
        )
        self._box(monkeypatch, elsewhere)

        result = geocode_location(
            city="", zone="champs élysées", raw_user_message="hotel champs élysées",
            proximity_lat=48.87, proximity_lon=2.31,
        )

        # Anchored on purpose: unanchored this would now be `geocode_ambiguous`
        # and the test would pass for the wrong reason, fencing nothing. On THIS
        # tier a failed echo degrades to `no_geocodable_location` (the
        # `geocode_echo_mismatch` error belongs to the tier-1 city path).
        assert result["ok"] is False
        assert result["error"] == "no_geocodable_location"


class TestSearchBoxIsScoped:
    """P0-2 fix 2 (audit §1 M3). The tier-2 lookup was worldwide and blind: no
    proximity (though the client accepts one) and a country that is only set
    when the user NAMED one. A perfect name match in the wrong country sails
    through the echo guard (M4), so the scope is the only separator.

    Since 2026-08-26 an unanchored zone-only request asks which city instead of
    resolving under egress-IP bias, so these cases carry a device fix: what they
    assert (the tier-2 scope) is what happens once the lookup is legitimately
    allowed to run."""

    def _box(self, monkeypatch, result=_CHAMPS):
        box = _FakeSearchBox(result)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)
        return box

    def test_country_guess_scopes_the_lookup(self, monkeypatch):
        _patch_multi(monkeypatch, [], inventory={})
        box = self._box(monkeypatch)

        geocode_location(
            city="", zone="champs élysées", raw_user_message="hotel",
            country_guess="FR", proximity_lat=48.87, proximity_lon=2.31,
        )

        assert box.countries == ["FR"]

    def test_locale_prior_scopes_it_when_there_is_no_guess(self, monkeypatch):
        _patch_multi(monkeypatch, [], inventory={})
        box = self._box(monkeypatch)

        geocode_location(city="", zone="champs élysées", raw_user_message="h", locale="fr-FR",
                         proximity_lat=48.87, proximity_lon=2.31)

        assert box.countries == ["FR"]

    def test_a_named_country_outranks_the_guess(self, monkeypatch):
        # country_code is the user's own words; the guess must never override it.
        _patch_multi(monkeypatch, [], inventory={})
        box = self._box(monkeypatch)

        geocode_location(
            city="", zone="champs élysées", raw_user_message="h",
            country_code="BE", country_guess="FR", locale="fr-FR",
            proximity_lat=48.87, proximity_lon=2.31,
        )

        assert box.countries == ["BE"]

    def test_gps_proximity_now_reaches_search_box(self, monkeypatch):
        _patch_multi(monkeypatch, [], inventory={})
        box = self._box(monkeypatch)

        geocode_location(
            city="", zone="champs élysées", raw_user_message="h",
            proximity_lat=48.87, proximity_lon=2.31,
        )

        assert box.proximities == ["2.31,48.87"]  # Mapbox order: lon,lat

    def test_tier_2_after_a_city_miss_is_scoped_too(self, monkeypatch):
        # The pre-existing tier-2 path (city + zone, v6 junk) must get the same
        # scope, not just the new zone-only path.
        junk = _c("Al Ain", "AE", "Abu Dhabi", ftype="neighborhood", lat=24.2, rank=0)
        _patch_multi(monkeypatch, [junk], inventory={24.2: 0})
        box = self._box(monkeypatch)

        geocode_location(
            city="Paris", zone="champs élysées", raw_user_message="h",
            country_guess="FR", proximity_lat=48.87, proximity_lon=2.31,
        )

        assert box.countries == ["FR"]
        assert box.proximities == ["2.31,48.87"]

    def test_a_malformed_guess_degrades_to_no_scope_never_a_wrong_one(self, monkeypatch):
        _patch_multi(monkeypatch, [], inventory={})
        box = self._box(monkeypatch)

        geocode_location(
            city="", zone="champs élysées", raw_user_message="h", country_guess="France",
            proximity_lat=48.87, proximity_lon=2.31,
        )

        assert box.countries == [None]


class TestCountryGuessIsASoftPrior:
    """P0-2 fix 3. The guess shares the locale prior's BOUNDED weight — a boost
    among candidates, never a filter, so a wrong guess costs a rank and can
    never erase the right answer."""

    def test_the_guess_reorders_a_tie_toward_the_guessed_country(self, monkeypatch):
        # Direct contrast with test_language_hint_never_feeds_the_country_prior:
        # SAME two candidates, US at Mapbox rank 0. A `language_hint="fr"` must
        # NOT move them (that test asserts options[0] is US); an explicit
        # `country_guess="FR"` MUST — that is the whole point of the reversal.
        # It stays a clarify: the boost is bounded, so it reorders the options
        # rather than deciding for the user. A guess never silently picks.
        us = _c("Clermont", "US", "Florida", lat=28.55, rank=0)
        fr = _c("Clermont", "FR", "Auvergne", lat=45.78, rank=1)
        _patch_multi(monkeypatch, [us, fr], inventory={28.55: 20, 45.78: 20})

        result = geocode_location(
            city="Clermont", raw_user_message="hotel in Clermont", country_guess="FR"
        )

        assert result["error"] == "geocode_ambiguous"
        assert result["diagnostics"]["options"][0]["country_code"] == "FR"

    def test_a_wrong_guess_cannot_filter_out_the_only_candidate(self, monkeypatch):
        # The decisive property: a hard filter would have returned nothing here.
        milan = _c("Milano", "IT", "Milan", lat=45.46, rank=0)
        _patch_multi(monkeypatch, [milan], inventory={45.46: 40})

        result = geocode_location(
            city="Milano", raw_user_message="hotel a Milano", country_guess="JP"
        )

        assert result["ok"] is True
        assert result["country_code"] == "IT"

    def test_a_named_country_still_hard_filters(self, monkeypatch):
        # country_code keeps its filter semantics; the guess did not soften it.
        us = _c("Clermont", "US", "Florida", lat=28.55, rank=0)
        _patch_multi(monkeypatch, [us], inventory={28.55: 20})

        result = geocode_location(
            city="Clermont", raw_user_message="hotel", country_code="FR", country_guess="US"
        )

        assert result["ok"] is False

    def test_a_malformed_guess_is_ignored_by_the_prior(self, monkeypatch):
        milan = _c("Milano", "IT", "Milan", lat=45.46, rank=0)
        _patch_multi(monkeypatch, [milan], inventory={45.46: 40})

        result = geocode_location(
            city="Milano", raw_user_message="h", country_guess="not-a-code"
        )

        assert result["ok"] is True
        assert result["country_code"] == "IT"


class TestCityIsNotAMandatoryParameter:
    """2026-08-26. `city: str` had NO default, so ADK declared it mandatory and
    rejected the whole tool call — "the following mandatory input parameters are
    not present: city" — every time the model omitted the key, which is exactly
    what it does when the user names a landmark and no city. 14 such dead turns
    in the Langfuse traces between 2026-08-15 and 08-26 (champs élysées, louvre,
    gare de lyon, eiffel tower, la défense, buckingham palace). This was read as
    extraction non-determinism ("~1 turn in 6"); it was a signature."""

    def test_the_tool_is_callable_with_no_city_argument_at_all(self, monkeypatch):
        _patch_multi(monkeypatch, [])
        poi = GeocodeResult(48.8698, 2.3078, "Champs-Élysées, Paris, France", "FR", "Île-de-France")
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _FakeSearchBox(poi))

        # No `city=` — the shape that used to fail before the function ran.
        result = geocode_location(zone="les champs élysées", country_guess="FR",
                                  raw_user_message="je cherche un hôtel autour des champs élysées")

        # Still callable (that is this class's subject, and the signature test
        # below is what actually fences the ADK bug). The OUTCOME changed on
        # 2026-08-26: unanchored, this now asks which city instead of resolving
        # under egress-IP bias — see TestUnanchoredZoneAsksForTheCity.
        assert result["ok"] is False
        assert result["error"] == "geocode_ambiguous"

    def test_city_has_a_default_so_adk_cannot_mark_it_required(self):
        import inspect

        missing = [
            name for name, p in inspect.signature(geocode_location).parameters.items()
            if p.default is inspect.Parameter.empty
        ]
        # ADK derives "mandatory input parameter" from "has no default value".
        assert missing == []

    def test_an_unresolved_landmark_is_not_reported_as_a_generic_location(self, monkeypatch):
        # The diagnostic used to say `generic_location_only` for ANY zone that
        # failed, including a real landmark — `is_generic_location_token("notre
        # dame")` is False, so it sent readers hunting a demotion that never
        # happened.
        _patch_multi(monkeypatch, [])

        result = geocode_location(city="", zone="notre dame", country_code="FR",
                                  raw_user_message="day use autour de notre dame",
                                  proximity_lat=48.85, proximity_lon=2.35)

        assert result["ok"] is False
        assert result["diagnostics"]["reason"] == "landmark_not_resolved"

    def test_a_genuinely_generic_zone_still_reports_generic(self, monkeypatch):
        _patch_multi(monkeypatch, [])

        result = geocode_location(city="", zone="gare", country_code="FR",
                                  raw_user_message="un hôtel près de la gare")

        assert result["ok"] is False
        assert result["diagnostics"]["reason"] == "generic_location_only"


class TestSearchBoxProximityIsNeverLeftToMapbox:
    """Mapbox documents, for `/search/searchbox/v1/forward`: "If not provided,
    the default is IP proximity." Sending no `proximity` therefore does not mean
    "unbiased" — it means "biased by whatever IP this container egresses from".
    That is what resolved "les champs élysées" to a shop of that name in Toulon,
    830 km away, on 2026-08-25 in production, while the identical arguments
    replayed from a laptop returned Paris (trace 5eec27af27b79ed4b87f4c325b563bbc)."""

    def test_a_verified_city_coordinate_is_sent_as_proximity_with_a_bare_query(self, monkeypatch):
        # v6 resolves the CITY but its pick fails the landmark echo, so tier 2
        # runs — and it must aim at the city we just verified, not at the
        # datacenter. Bare query on purpose: appending the city floods the list
        # with businesses named after the landmark, and one of them becomes the
        # `resolved_place` the customer sees.
        paris = _c("Paris", "FR", "Île-de-France", lat=48.8566, lon=2.3522)
        _patch_multi(monkeypatch, [paris], inventory={48.8566: 780})
        poi = GeocodeResult(48.8698, 2.3078, "Champs-Élysées, 75008 Paris, France", "FR", "IdF")
        box = _FakeSearchBox(poi)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)

        result = geocode_location(city="Paris", zone="les champs élysées",
                                  raw_user_message="un hôtel vers les champs élysées à paris")

        assert result["ok"] is True
        assert box.calls[-1][0] == "les champs élysées"        # bare, not "…, Paris"
        assert box.proximities[-1] == "2.3522,48.8566"         # lon,lat of the verified city

    def test_without_any_coordinate_the_city_is_folded_into_the_query_instead(self, monkeypatch):
        # No GPS, and v6 produced nothing that echoes the city — so there is no
        # coordinate to aim with. Folding the city into the query is the only
        # remaining way to say which city we mean. Costs label quality, which is
        # why it is the fallback and not the default.
        _patch_multi(monkeypatch, [])
        poi = GeocodeResult(48.8698, 2.3078, "Champs-Élysées, 75008 Paris, France", "FR", "IdF")
        box = _FakeSearchBox(poi)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)

        result = geocode_location(city="Paris", zone="les champs élysées",
                                  raw_user_message="un hôtel vers les champs élysées à paris")

        assert result["ok"] is True
        assert box.calls[-1][0] == "les champs élysées, Paris"
        assert box.proximities[-1] is None

    def test_a_gps_fix_still_wins_over_the_city_coordinate(self, monkeypatch):
        paris = _c("Paris", "FR", "Île-de-France", lat=48.8566, lon=2.3522)
        _patch_multi(monkeypatch, [paris], inventory={48.8566: 780})
        poi = GeocodeResult(48.8698, 2.3078, "Champs-Élysées, 75008 Paris, France", "FR", "IdF")
        box = _FakeSearchBox(poi)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)

        result = geocode_location(city="Paris", zone="les champs élysées",
                                  raw_user_message="un hôtel vers les champs élysées à paris",
                                  proximity_lat=48.87, proximity_lon=2.31)

        assert result["ok"] is True
        assert box.proximities[-1] == "2.31,48.87"


class TestPoiAnchorCoherenceGuard:
    """Guard #14 (`poi_anchor_coherence`). The echo-back guard validates the
    NAME, which a homonym passes perfectly — audit M4, "the name is right, the
    place is wrong". This validates the PLACE against the turn's own anchor."""

    def test_a_poi_far_from_the_verified_city_is_rejected(self, monkeypatch):
        paris = _c("Paris", "FR", "Île-de-France", lat=48.8566, lon=2.3522)
        _patch_multi(monkeypatch, [paris], inventory={48.8566: 780})
        # Echoes "champs élysées" perfectly — and sits in Toulon, 830 km away.
        toulon = GeocodeResult(43.1215, 5.9322, "Champs Elysées, 32 Rue d'Alger, 83000 Toulon,"
                               " France", "FR", "PACA")
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _FakeSearchBox(toulon))

        result = geocode_location(city="Paris", zone="les champs élysées",
                                  raw_user_message="un hôtel vers les champs élysées à paris")

        assert result["ok"] is False
        assert "poi_anchor_coherence" in result["guards_fired"]

    def test_a_landmark_legitimately_outside_the_city_centre_is_kept(self, monkeypatch):
        # Disneyland Paris is 32 km from central Paris. The threshold is
        # calibrated to keep it: this guard catches gross mis-resolutions, and
        # the city-in-the-query / proximity fix handles the near ones.
        paris = _c("Paris", "FR", "Île-de-France", lat=48.8566, lon=2.3522)
        _patch_multi(monkeypatch, [paris], inventory={48.8566: 780})
        park = GeocodeResult(48.8674, 2.7836, "Disneyland Paris, 77700 Chessy, France", "FR", "IdF")
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _FakeSearchBox(park))

        result = geocode_location(city="Paris", zone="disneyland paris",
                                  raw_user_message="hôtel près de disneyland paris")

        assert result["ok"] is True
        assert "poi_anchor_coherence" not in (result.get("guards_fired") or [])

    def test_with_no_anchor_at_all_the_turn_never_reaches_this_guard(self, monkeypatch):
        # This guard's documented limit was "with no anchor there is nothing to
        # compare against, so it cannot fire" — which is exactly how the Toulon
        # POI got accepted. Since 2026-08-26 that shape is gated upstream: with
        # no city, no metro and no device fix the tool asks which city, so the
        # unguardable case no longer reaches this guard at all.
        _patch_multi(monkeypatch, [])
        far = GeocodeResult(43.1215, 5.9322, "Champs Elysées, 83000 Toulon, France", "FR", "PACA")
        box = _FakeSearchBox(far)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)

        result = geocode_location(city="", zone="les champs élysées", country_guess="FR",
                                  raw_user_message="autour des champs élysées")

        assert result["ok"] is False
        assert result["error"] == "geocode_ambiguous"
        assert box.calls == []          # the Toulon POI is never even fetched
        assert "poi_anchor_coherence" not in (result.get("guards_fired") or [])


class TestRadiusFollowsTheRequestNotTheGeocoder:
    """`inject_landmark_radius` tightens the search disc to 3 km only when
    `distance_origin_type == "poi"`. That used to depend on WHICH TIER answered,
    so the same landmark got a 3 km disc via Search Box and a 20 km one via v6
    (`neighborhood` → `city_centroid`) — and `hotels_within_km` failed for
    reasons that had nothing to do with the geocode being right."""

    def test_a_named_zone_resolved_by_tier_1_is_still_a_poi_origin(self, monkeypatch):
        quartier = _c("Champs-Élysées", "FR", "Île-de-France",
                      ftype="neighborhood", lat=48.8698, lon=2.3078)
        _patch_multi(monkeypatch, [quartier], inventory={48.8698: 780})

        result = geocode_location(city="Paris", zone="Champs-Élysées",
                                  raw_user_message="un hôtel vers les champs élysées à paris")

        assert result["ok"] is True
        assert result["distance_origin_type"] == "poi"

    def test_a_generic_zone_keeps_the_city_centroid_origin(self, monkeypatch):
        boston = _c("Boston", "US", "Massachusetts", lat=42.3601, lon=-71.0589)
        _patch_multi(monkeypatch, [boston], inventory={42.3601: 200})

        result = geocode_location(city="Boston", zone="airport",
                                  raw_user_message="hotel near the airport in Boston tomorrow")

        assert result["ok"] is True
        assert result["distance_origin_type"] == "city_centroid"

    def test_a_plain_city_search_keeps_the_city_centroid_origin(self, monkeypatch):
        paris = _c("Paris", "FR", "Île-de-France", lat=48.8566, lon=2.3522)
        _patch_multi(monkeypatch, [paris], inventory={48.8566: 780})

        result = geocode_location(city="Paris", raw_user_message="un hôtel à paris demain")

        assert result["ok"] is True
        assert result["distance_origin_type"] == "city_centroid"


class TestCityAnchorMustBeInventoryCredible:
    """Found on the first post-deploy check, 2026-08-26. The city anchor aims
    the Search-Box lookup AND feeds guard #14's veto, so a candidate that merely
    ECHOES the city's name is not enough — that is the S-G9 micro-homonym trap
    the resolver's own docstring warns about, reintroduced in a new place.

    Real case: "gare de lyon" + city "Paris". The only v6 candidate echoing
    "Paris" was a neighbourhood literally named Paris in ROANNE (2 hotels
    nearby, 390 km out). It became "the verified Paris", aimed Search Box at
    Roanne, which returned Lyon stations, which failed the echo — and the turn
    died on a clarify."""

    def test_a_micro_homonym_of_the_city_is_not_a_valid_anchor(self, monkeypatch):
        roanne_paris = _c("Paris", "FR", "Loire", ftype="neighborhood", lat=46.046, lon=4.070)
        garde_lyon = _c("La Garde", "FR", "Rhône", ftype="neighborhood", lat=45.760, lon=4.796)
        _patch_multi(monkeypatch, [garde_lyon, roanne_paris],
                     inventory={45.760: 80, 46.046: 2})   # Roanne is below the tier
        poi = GeocodeResult(48.8443, 2.3743, "Gare de Lyon, 75012 Paris, France", "FR", "IdF")
        box = _FakeSearchBox(poi)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)

        result = geocode_location(city="Paris", zone="gare de lyon", country_code="FR",
                                  raw_user_message="hotel pres de la gare de lyon demain")

        assert result["ok"] is True
        # No credible anchor ⇒ no proximity, and the city is folded into the
        # query instead. Aiming at Roanne is exactly what must not happen.
        assert box.proximities[-1] is None
        assert box.calls[-1][0] == "gare de lyon, Paris"

    def test_an_inventory_credible_city_candidate_is_still_used_as_the_anchor(self, monkeypatch):
        real_paris = _c("Paris", "FR", "Île-de-France", ftype="place", lat=48.8566, lon=2.3522)
        _patch_multi(monkeypatch, [real_paris], inventory={48.8566: 780})
        poi = GeocodeResult(48.8698, 2.3078, "Champs-Élysées, 75008 Paris, France", "FR", "IdF")
        box = _FakeSearchBox(poi)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)

        result = geocode_location(city="Paris", zone="les champs élysées",
                                  raw_user_message="un hôtel vers les champs élysées à paris")

        assert result["ok"] is True
        assert box.proximities[-1] == "2.3522,48.8566"
        assert box.calls[-1][0] == "les champs élysées"   # bare query, keeps the clean label


class TestUnanchoredZoneAsksForTheCity:
    """2026-08-26, found by the post-deploy verification of `fa08813` in prod.

    `« pres de la gare de lyon demain »` came back with 5 hotels in LYON — a
    Paris station answered with another city, confidently. Measured from the
    prod container, the candidate list for a bare "gare de lyon" is ten Lyon
    tram stops and the Paris station is NOT in it (it appears only once the
    `proximity` bias already points at Paris), so the ranker cannot recover it
    and no honest option list can be built from what came back. The same turn
    with "à paris" lands 0,5 km from the station, which is what proves the
    resolver itself is sound and the missing `city` is the whole defect.

    Product decision: when the doubt is real and undecidable, ask which city
    rather than ship an egress-IP-dependent guess as a fact."""

    def test_a_named_zone_with_no_anchor_asks_which_city(self, monkeypatch):
        _patch_multi(monkeypatch, [])
        poi = GeocodeResult(45.7695, 4.8530, "Masséna, 69006 Lyon, France", "FR", "ARA")
        box = _FakeSearchBox(poi)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)

        result = geocode_location(zone="gare de lyon", country_code="FR", locale="fr-FR",
                                  raw_user_message="hôtel pres de la gare de lyon demain")

        assert result["ok"] is False
        assert result["error"] == "geocode_ambiguous"
        assert "gare de lyon" in result["diagnostics"]["question"]
        # The Lyon candidate must not be offered back: it IS the wrong answer.
        assert result["diagnostics"]["options"] == []
        # And the question costs no geocoder call at all — we ask BEFORE looking
        # up, precisely because the lookup has nothing to aim at.
        assert box.calls == []

    def test_a_device_fix_still_resolves_the_same_zone(self, monkeypatch):
        # The P0-2 win is preserved wherever an anchor exists: with a GPS fix the
        # ranker has something Mapbox cannot bias, so nothing is asked.
        _patch_multi(monkeypatch, [], inventory={48.8698: 210})
        poi = GeocodeResult(48.8698, 2.3078, "Champs-Élysées, 75008 Paris, France", "FR", "IdF")
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _FakeSearchBox(poi))

        result = geocode_location(zone="les champs élysées", country_guess="FR",
                                  proximity_lat=48.87, proximity_lon=2.31,
                                  raw_user_message="un hôtel autour des champs élysées")

        assert result["ok"] is True
        assert result["latitude"] == 48.8698
        assert result["distance_origin_type"] == "poi"

    def test_a_named_zone_with_a_city_is_untouched_by_the_gate(self, monkeypatch):
        # Fence for the dominant prod path (tours A/D): a city was given, so the
        # lookup is aimed and the gate must stay out of the way.
        paris = _c("Paris", "FR", "Île-de-France", ftype="place", lat=48.8566, lon=2.3522)
        _patch_multi(monkeypatch, [paris], inventory={48.8566: 780})
        poi = GeocodeResult(48.8443, 2.3743, "Gare de Lyon, 75012 Paris, France", "FR", "IdF")
        box = _FakeSearchBox(poi)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)

        result = geocode_location(city="Paris", zone="gare de lyon", locale="fr-FR",
                                  raw_user_message="hôtel pres de la gare de lyon a paris demain")

        # Which tier answers depends on what v6 returns for "gare de lyon, Paris"
        # (in prod it is tier 2, here the fake's v6 candidate echoes and wins) —
        # what this fences is only that the gate stayed out of the way.
        assert result["ok"] is True
        assert "error" not in result

    def test_the_question_speaks_the_conversation_language(self, monkeypatch):
        _patch_multi(monkeypatch, [])
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: _FakeSearchBox(None))

        fr = geocode_location(zone="gare de lyon", locale="fr-FR", raw_user_message="x")
        en = geocode_location(zone="times square", locale="en-US", raw_user_message="x")

        assert "dans quelle ville" in fr["diagnostics"]["question"]
        assert "which city" in en["diagnostics"]["question"]
