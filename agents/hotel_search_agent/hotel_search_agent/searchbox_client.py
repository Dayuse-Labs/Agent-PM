"""Mapbox Search Box `/forward` client — the POI/landmark tier-2 fallback (S-G3, A2-b).

Arbitration A2-b: adopt Search Box ONLY IF a live probe shows Geocoding v6 fails
on our real zone/POI cases. Probed live 2026-07-23 — it does: "La Défense" and
"Tour Eiffel" return junk under v6 (v6 dropped POI support entirely), while
Search Box `/forward` resolves them correctly as `poi` features. So this is a
narrow, deterministic FALLBACK: `geocode_tool` calls it only when tier-1 (v6
multi-candidate + `geo_resolver`) produced no acceptable place AND the request
carried a zone/landmark string — never on the common city-search path (Search
Box is a separate billing SKU, and for cities/regions it is WORSE — probed:
"Orange County" → airports, "Milano" → French POIs).

Same budget posture as `MapboxClient` (single-owner rule): 1.5 s, 1 retry, then
give up — one extra call on the rare fallback path, never a loop.
"""
from __future__ import annotations

from collections import OrderedDict

import httpx

from hotel_search_agent.mapbox_client import GeocodeResult

SEARCHBOX_URL = "https://api.mapbox.com/search/searchbox/v1/forward"

# POIs and named zones only — this tier exists precisely for what v6 can't do.
DEFAULT_TYPES = "poi,address,neighborhood,locality,place"


class SearchBoxClient:
    def __init__(
        self,
        access_token: str,
        *,
        timeout_seconds: float = 1.5,
        cache_maxsize: int = 128,
        client: httpx.Client | None = None,
    ) -> None:
        self._token = access_token
        self._timeout = timeout_seconds
        self._client = client or httpx.Client()
        self._cache_maxsize = cache_maxsize
        self._cache: OrderedDict[tuple, GeocodeResult | None] = OrderedDict()

    def forward(
        self,
        query: str,
        *,
        country: str | None = None,
        language: str | None = None,
        proximity: str | None = None,
        types: str = DEFAULT_TYPES,
    ) -> GeocodeResult | None:
        """Best POI/landmark match for `query`, or None (transient failure or no
        match). The caller runs the same echo sanity-check it runs on a tier-1
        result before trusting the coordinates."""
        key = (query, country, language, proximity, types)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        params: dict[str, str | int] = {
            "q": query,
            "types": types,
            "limit": 1,
            "access_token": self._token,
        }
        if country:
            params["country"] = country.lower()
        if language:
            params["language"] = language
        if proximity:
            params["proximity"] = proximity
        result = self._forward_with_retry(params, fallback=query)
        self._remember(key, result)
        return result

    def _remember(self, key: tuple, value: GeocodeResult | None) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_maxsize:
            self._cache.popitem(last=False)

    def _forward_with_retry(self, params: dict[str, str | int], *, fallback: str) -> GeocodeResult | None:
        attempts = 2
        for attempt in range(attempts):
            try:
                response = self._client.get(SEARCHBOX_URL, params=params, timeout=self._timeout)
                response.raise_for_status()
            except httpx.HTTPError:
                if attempt == attempts - 1:
                    return None
                continue
            return self._parse(response.json(), fallback=fallback)
        return None

    @staticmethod
    def _parse(data: dict, *, fallback: str) -> GeocodeResult | None:
        features = data.get("features") or []
        if not features:
            return None
        feature = features[0]
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) >= 2:
            lat, lng = float(coords[1]), float(coords[0])
        else:
            pc = props.get("coordinates") or {}
            if pc.get("latitude") is None or pc.get("longitude") is None:
                return None
            lat, lng = float(pc["latitude"]), float(pc["longitude"])
        context = props.get("context") or {}
        country_ctx = context.get("country") or {}
        region_ctx = context.get("region") or {}
        # A POI's `full_address` is its CONTAINING commune ("92800 Puteaux, France"
        # for "La Défense") — it doesn't echo the landmark the user named. Prefix
        # the POI name so the SAME echo-back guard the caller runs on a tier-1
        # result validates this one ("La Défense" must appear in place_name).
        name = str(props.get("name") or "")
        full_address = str(props.get("full_address") or "")
        if name and full_address and name.lower() not in full_address.lower():
            place_name = f"{name}, {full_address}"
        else:
            place_name = full_address or name or fallback
        return GeocodeResult(
            latitude=lat,
            longitude=lng,
            place_name=place_name,
            country_code=str(country_ctx.get("country_code") or "").upper(),
            region=str(region_ctx.get("name") or region_ctx.get("region_code") or ""),
        )
