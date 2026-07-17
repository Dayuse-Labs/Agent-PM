"""MapboxClient tests — httpx.MockTransport only, no real network call."""
from __future__ import annotations

import httpx

from hotel_search_agent.mapbox_client import GeocodeResult, MapboxClient

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
