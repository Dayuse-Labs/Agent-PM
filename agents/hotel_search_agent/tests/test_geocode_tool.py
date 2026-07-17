"""geocode_location — composition of the 3 geo guards + Mapbox, tested with a
fake client (no network): degrade honestly on every rejection path, never
raise.
"""
from __future__ import annotations

from hotel_search_agent import geocode_tool
from hotel_search_agent.geocode_tool import geocode_location
from hotel_search_agent.mapbox_client import GeocodeResult


class FakeMapboxClient:
    def __init__(self, result: GeocodeResult | None):
        self.result = result
        self.calls: list[tuple] = []

    def geocode(self, query, *, country=None, **kwargs):
        self.calls.append((query, country))
        return self.result


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
