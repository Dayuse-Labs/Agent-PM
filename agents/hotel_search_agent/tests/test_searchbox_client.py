"""SearchBoxClient — the POI/landmark tier-2 fallback (S-G3, A2-b). MockTransport
only, no real network."""
from __future__ import annotations

import httpx

from hotel_search_agent.searchbox_client import SearchBoxClient

LA_DEFENSE = {
    "features": [
        {
            "geometry": {"coordinates": [2.2387, 48.8918]},
            "properties": {
                "name": "La Défense",
                "feature_type": "poi",
                "full_address": "92800 Puteaux, France",
                "place_formatted": "France",
                "context": {"country": {"country_code": "fr"}, "region": {"name": "Île-de-France"}},
            },
        }
    ]
}


def _client(handler) -> SearchBoxClient:
    return SearchBoxClient("tok", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_parses_the_top_poi_into_a_geocode_result():
    client = _client(lambda request: httpx.Response(200, json=LA_DEFENSE))
    result = client.forward("La Défense", country="fr")
    assert result is not None
    assert (round(result.latitude, 4), round(result.longitude, 4)) == (48.8918, 2.2387)
    # POI name prefixed so the caller's echo-back guard can validate it (the raw
    # full_address is only the containing commune, "92800 Puteaux, France").
    assert result.place_name == "La Défense, 92800 Puteaux, France"
    assert result.country_code == "FR"


def test_hits_the_searchbox_forward_endpoint_with_params():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"features": []})

    client = _client(handler)
    client.forward("Tour Eiffel", country="fr", language="fr")
    assert seen["path"].endswith("/search/searchbox/v1/forward")
    assert seen["params"]["country"] == "fr"
    assert seen["params"]["language"] == "fr"
    assert seen["params"]["limit"] == "1"


def test_no_features_returns_none():
    client = _client(lambda request: httpx.Response(200, json={"features": []}))
    assert client.forward("nothing here") is None


def test_transient_failure_retries_once_then_none():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectTimeout("timed out", request=request)

    client = _client(handler)
    assert client.forward("La Défense") is None
    assert calls["n"] == 2


def test_result_is_cached():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=LA_DEFENSE)

    client = _client(handler)
    client.forward("La Défense", country="fr")
    client.forward("La Défense", country="fr")
    assert calls["n"] == 1
