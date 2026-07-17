"""Real Mapbox Geocoding API v6 client — this leaf's one owned outbound
dependency for turning a destination string into coordinates (MCP_B2C's
`search_offers` requires numeric lat/lon; it does no geocoding itself).

Budget (CLAUDE.md, single-owner rule): 1.5 s timeout, 1 retry, then give up —
a guard never re-runs a loop. A small in-memory cache avoids re-geocoding the
same destination twice within one process; it holds no cross-turn PROFILE
state (decision B3 — this leaf is stateless), just a bounded lookup cache.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

import httpx

GEOCODE_URL = "https://api.mapbox.com/search/geocode/v6/forward"

# Types Dayuse cares about: no addresses/POIs — a destination search resolves
# to a place, not a street number.
DEFAULT_TYPES = "place,locality,neighborhood"


@dataclass(frozen=True)
class GeocodeResult:
    """One geocoded destination — `place_name` is what `geo_guards.geocode_echo_matches`
    validates against the request."""

    latitude: float
    longitude: float
    place_name: str
    country_code: str
    region: str


class MapboxClient:
    """Synchronous forward geocoder: 1 request + 1 retry, each bounded by
    `timeout_seconds`; results (including "not found") are cached in memory,
    bounded to `cache_maxsize` entries (oldest evicted first)."""

    def __init__(
        self,
        access_token: str,
        *,
        timeout_seconds: float = 1.5,
        cache_maxsize: int = 256,
        client: httpx.Client | None = None,
    ) -> None:
        self._token = access_token
        self._timeout = timeout_seconds
        self._client = client or httpx.Client()
        self._cache_maxsize = cache_maxsize
        self._cache: OrderedDict[tuple, GeocodeResult | None] = OrderedDict()

    def geocode(
        self,
        query: str,
        *,
        country: str | None = None,
        language: str = "en",
        types: str = DEFAULT_TYPES,
    ) -> GeocodeResult | None:
        """Geocode `query` (limit=1 — the caller validates the single result
        with `geo_guards.geocode_echo_matches`, it never picks among several).
        Returns None on a transient failure (timeout/network/5xx) that
        survived the retry, or when Mapbox has no match — the caller must
        degrade honestly in either case, never fabricate coordinates.
        """
        key = (query, country, language, types)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        result = self._geocode_with_retry(query, country=country, language=language, types=types)
        self._remember(key, result)
        return result

    def _remember(self, key: tuple, value: GeocodeResult | None) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_maxsize:
            self._cache.popitem(last=False)

    def _geocode_with_retry(
        self, query: str, *, country: str | None, language: str, types: str
    ) -> GeocodeResult | None:
        params: dict[str, str | int] = {
            "q": query,
            "types": types,
            "limit": 1,
            "language": language or "en",
            "access_token": self._token,
        }
        if country:
            params["country"] = country.lower()

        attempts = 2  # 1 initial call + 1 retry
        for attempt in range(attempts):
            try:
                response = self._client.get(GEOCODE_URL, params=params, timeout=self._timeout)
                response.raise_for_status()
            except httpx.HTTPError:
                if attempt == attempts - 1:
                    return None
                continue
            return self._parse(response.json(), fallback=query)
        return None

    @staticmethod
    def _parse(data: dict, *, fallback: str) -> GeocodeResult | None:
        features = data.get("features") or []
        if not features:
            return None
        feature = features[0]
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            return None
        lng, lat = coords[0], coords[1]
        context = props.get("context") or {}
        country_ctx = context.get("country") or {}
        region_ctx = context.get("region") or {}
        return GeocodeResult(
            latitude=lat,
            longitude=lng,
            place_name=str(props.get("full_address") or props.get("name") or fallback),
            country_code=str(country_ctx.get("country_code") or "").upper(),
            region=str(region_ctx.get("region_code") or region_ctx.get("name") or ""),
        )
