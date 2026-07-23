"""geocode_location — composition of the 3 geo guards + Mapbox, tested with a
fake client (no network): degrade honestly on every rejection path, never
raise.
"""
from __future__ import annotations

import httpx
import pytest

from hotel_search_agent import geocode_tool
from hotel_search_agent.geocode_tool import geocode_location
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

    def geocode_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, country))
        self.langs.append(language)
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
