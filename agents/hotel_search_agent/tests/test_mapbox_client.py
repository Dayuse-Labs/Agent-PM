"""MapboxClient tests — httpx.MockTransport only, no real network call."""
from __future__ import annotations

import httpx

from hotel_search_agent.mapbox_client import (
    CANDIDATE_TYPES,
    DEFAULT_CANDIDATE_LIMIT,
    GeocodeResult,
    MapboxClient,
)

FLORENCE_KY_RESPONSE = {
    "features": [
        {
            "geometry": {"coordinates": [-84.6266, 38.9989]},
            "properties": {
                "full_address": "Florence, Kentucky, United States",
                "context": {
                    "country": {"country_code": "us"},
                    "region": {"region_code": "KY", "name": "Kentucky"},
                },
            },
        }
    ]
}

EMPTY_RESPONSE: dict = {"features": []}


def _client_with(handler) -> MapboxClient:
    transport = httpx.MockTransport(handler)
    return MapboxClient("test-token", client=httpx.Client(transport=transport))


class TestSuccessfulGeocode:
    def test_parses_place_name_coordinates_and_country(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.startswith("/search/geocode/v6/forward")
            return httpx.Response(200, json=FLORENCE_KY_RESPONSE)

        client = _client_with(handler)
        result = client.geocode("florence kentucky")

        assert result == GeocodeResult(
            latitude=38.9989,
            longitude=-84.6266,
            place_name="Florence, Kentucky, United States",
            country_code="US",
            region="KY",
        )

    def test_no_features_returns_none(self):
        client = _client_with(lambda request: httpx.Response(200, json=EMPTY_RESPONSE))
        assert client.geocode("nonsense query") is None

    def test_request_carries_limit_one_and_token(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json=EMPTY_RESPONSE)

        client = _client_with(handler)
        client.geocode("Miami", country="US", language="fr")

        assert seen["params"]["limit"] == "1"
        assert seen["params"]["access_token"] == "test-token"
        assert seen["params"]["country"] == "us"
        assert seen["params"]["language"] == "fr"

    def test_no_country_filter_when_country_omitted(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json=EMPTY_RESPONSE)

        client = _client_with(handler)
        client.geocode("Victoria BC")

        assert "country" not in seen["params"]


class TestRetryAndTimeoutBudget:
    def test_default_timeout_is_1_5_seconds(self):
        client = MapboxClient("tok")
        assert client._timeout == 1.5

    def test_retries_once_then_succeeds(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectTimeout("timed out", request=request)
            return httpx.Response(200, json=FLORENCE_KY_RESPONSE)

        client = _client_with(handler)
        result = client.geocode("florence kentucky")

        assert calls["n"] == 2
        assert result is not None
        assert result.place_name == "Florence, Kentucky, United States"

    def test_gives_up_after_one_retry_and_returns_none(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            raise httpx.ConnectTimeout("timed out", request=request)

        client = _client_with(handler)
        result = client.geocode("florence kentucky")

        # 1 initial attempt + 1 retry, never a third — a guard never re-runs a loop.
        assert calls["n"] == 2
        assert result is None

    def test_5xx_response_is_retried_then_gives_up(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(503, json={"message": "upstream unavailable"})

        client = _client_with(handler)
        result = client.geocode("florence kentucky")

        assert calls["n"] == 2
        assert result is None


class TestCache:
    def test_second_call_with_same_params_hits_cache_not_transport(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json=FLORENCE_KY_RESPONSE)

        client = _client_with(handler)
        first = client.geocode("florence kentucky")
        second = client.geocode("florence kentucky")

        assert calls["n"] == 1
        assert first == second

    def test_negative_result_is_also_cached(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json=EMPTY_RESPONSE)

        client = _client_with(handler)
        client.geocode("nowhere")
        client.geocode("nowhere")

        assert calls["n"] == 1

    def test_different_country_is_a_different_cache_key(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json=FLORENCE_KY_RESPONSE)

        client = _client_with(handler)
        client.geocode("florence", country="US")
        client.geocode("florence", country="IT")

        assert calls["n"] == 2

    def test_cache_is_bounded_and_evicts_oldest(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=FLORENCE_KY_RESPONSE)

        transport = httpx.MockTransport(handler)
        client = MapboxClient("tok", cache_maxsize=2, client=httpx.Client(transport=transport))

        client.geocode("a")
        client.geocode("b")
        client.geocode("c")  # evicts "a"

        assert len(client._cache) == 2
        assert ("a", None, "en", "place,locality,neighborhood") not in client._cache
        assert ("c", None, "en", "place,locality,neighborhood") in client._cache


def _feature(name, ftype, cc, region, lon, lat, *, place_formatted, full_address, bbox=None):
    props = {
        "name": name,
        "feature_type": ftype,
        "place_formatted": place_formatted,
        "full_address": full_address,
        "context": {"country": {"country_code": cc}, "region": {"name": region}},
    }
    if bbox is not None:
        props["bbox"] = bbox
    return {"geometry": {"coordinates": [lon, lat]}, "properties": props}


VICTORIA_MULTI = {
    "features": [
        _feature("Victoria", "place", "ca", "British Columbia", -123.36, 48.42,
                 place_formatted="British Columbia, Canada",
                 full_address="Victoria, British Columbia, Canada",
                 bbox=[-123.5, 48.3, -123.2, 48.5]),
        _feature("Victoria", "region", "au", "Victoria", 144.0, -37.0,
                 place_formatted="Australia",
                 full_address="Victoria, Australia"),
        _feature("Victoria", "place", "us", "Texas", -96.99, 28.80,
                 place_formatted="Texas, United States",
                 full_address="Victoria, Texas, United States"),
    ]
}


class TestGeocodeCandidates:
    def test_returns_all_parsed_candidates_with_rank(self):
        client = _client_with(lambda request: httpx.Response(200, json=VICTORIA_MULTI))
        cands = client.geocode_candidates("Victoria")
        assert len(cands) == 3
        assert [c.rank for c in cands] == [0, 1, 2]
        bc = cands[0]
        assert bc.name == "Victoria"
        assert bc.country_code == "CA"
        assert bc.region == "British Columbia"
        assert bc.feature_type == "place"
        assert bc.place_formatted == "British Columbia, Canada"
        assert bc.place_name == "Victoria, British Columbia, Canada"
        assert bc.bbox == (-123.5, 48.3, -123.2, 48.5)
        assert (bc.latitude, bc.longitude) == (48.42, -123.36)

    def test_bbox_absent_is_none(self):
        client = _client_with(lambda request: httpx.Response(200, json=VICTORIA_MULTI))
        au = client.geocode_candidates("Victoria")[1]
        assert au.bbox is None

    def test_request_carries_limit_types_autocomplete_and_optional_params(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json={"features": []})

        client = _client_with(handler)
        client.geocode_candidates("Lisboa", country="PT", language="pt", proximity="ip")
        p = seen["params"]
        assert p["limit"] == str(DEFAULT_CANDIDATE_LIMIT)
        assert p["types"] == CANDIDATE_TYPES
        assert p["autocomplete"] == "false"
        assert p["language"] == "pt"
        assert p["country"] == "pt"
        assert p["proximity"] == "ip"

    def test_optional_params_omitted_when_absent(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json={"features": []})

        client = _client_with(handler)
        client.geocode_candidates("Victoria")
        assert "language" not in seen["params"]
        assert "country" not in seen["params"]
        assert "proximity" not in seen["params"]

    def test_empty_features_returns_empty_list(self):
        client = _client_with(lambda request: httpx.Response(200, json={"features": []}))
        assert client.geocode_candidates("nowhere") == []

    def test_transient_failure_returns_empty_list_after_one_retry(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            raise httpx.ConnectTimeout("timed out", request=request)

        client = _client_with(handler)
        assert client.geocode_candidates("Victoria") == []
        assert calls["n"] == 2

    def test_candidates_are_cached(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json=VICTORIA_MULTI)

        client = _client_with(handler)
        client.geocode_candidates("Victoria")
        client.geocode_candidates("Victoria")
        assert calls["n"] == 1

    def test_geocode_limit_one_path_is_unaffected_by_candidate_cache(self):
        # The two entry points use distinct cache-key shapes: calling one must not
        # serve the other a stale value.
        client = _client_with(lambda request: httpx.Response(200, json=VICTORIA_MULTI))
        single = client.geocode("Victoria")
        cands = client.geocode_candidates("Victoria")
        assert isinstance(single, GeocodeResult)
        assert single.place_name == "Victoria, British Columbia, Canada"
        assert len(cands) == 3


def test_localized_address_keeps_provider_name_for_identity():
    from hotel_search_agent.geo_guards import geocode_echo_matches

    for name, address in (("Hong Kong", "香港"), ("Kifisia", "Κηφισιά, Αττική")):
        payload = {"features": [{"geometry": {"coordinates": [114.16, 22.28]},
                                "properties": {"name": name, "full_address": address}}]}
        client = _client_with(lambda request: httpx.Response(200, json=payload))
        single = client.geocode(name, language="zh")
        candidates = client.geocode_candidates(name, language="zh")
        assert single is not None and len(candidates) == 1
        for result in (single, candidates[0]):
            assert name in result.place_name and address in result.place_name
            assert geocode_echo_matches(result.place_name, city=None, zone=name,
                                        state_hint=None, require_all_tokens=True)
