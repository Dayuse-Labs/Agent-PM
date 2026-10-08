"""Real Mapbox Geocoding API v6 client — this leaf's one owned outbound
dependency for turning a destination string into coordinates (MCP_B2C's
`search_offers` requires numeric lat/lon; it does no geocoding itself).

Budget (CLAUDE.md, single-owner rule): 1.5 s timeout, 1 retry, then give up —
a guard never re-runs a loop. A small in-memory cache avoids re-geocoding the
same destination twice within one process; it holds no cross-turn PROFILE
state (decision B3 — this leaf is stateless), just a bounded lookup cache.

Two entry points:
- `geocode()` — the original limit=1 convenience (accept/reject a single result
  via `geo_guards.geocode_echo_matches`); unchanged.
- `geocode_candidates()` — S-G3: returns the FULL candidate list (default
  limit=10, Mapbox's own max), each parsed with the fields the deterministic
  `geo_resolver` needs (feature_type, place_formatted, ISO country/region,
  bbox, rank). v6 returns NO numeric relevance score for place features (probed
  live 2026-07-23 — `match_code`/`confidence` are address-only), so list
  position is the only relevance proxy the API hands us; the ranking is ours.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import httpx
from b2c_common.observability import mark_level

GEOCODE_URL = "https://api.mapbox.com/search/geocode/v6/forward"

# Types Dayuse cares about: no addresses/POIs — a destination search resolves
# to a place, not a street number. `geocode_candidates` widens this to also
# include district/region so county-type ("Orange County" → district, probed
# live) and state-type destinations survive tier-1 (POIs stay Search-Box turf).
DEFAULT_TYPES = "place,locality,neighborhood"
CANDIDATE_TYPES = "place,locality,neighborhood,district,region"

# Mapbox v6 default limit is already 5; 10 is its documented max — the old
# limit=1 threw away candidates the API returns for free.
DEFAULT_CANDIDATE_LIMIT = 10


@dataclass(frozen=True)
class GeocodeResult:
    """One geocoded destination — `place_name` is what `geo_guards.geocode_echo_matches`
    validates against the request."""

    latitude: float
    longitude: float
    place_name: str
    country_code: str
    region: str


@dataclass(frozen=True)
class GeocodeCandidate:
    """One of the ≤10 candidates Mapbox returned, with every field the
    deterministic `geo_resolver` re-ranks on. `place_name` (full_address) is
    kept for the echo-back sanity check on the CHOSEN candidate; `place_formatted`
    (the context without the name — "British Columbia, Canada") is the ready-made
    clarify-question label."""

    latitude: float
    longitude: float
    name: str
    place_name: str
    place_formatted: str
    feature_type: str
    country_code: str
    region: str
    bbox: tuple[float, float, float, float] | None
    rank: int
    mapbox_id: str = ""
    administrative_code: str = ""
    wikidata_id: str = ""
    parent_ids: tuple[str, ...] = ()

    def as_result(self) -> GeocodeResult:
        return GeocodeResult(
            latitude=self.latitude,
            longitude=self.longitude,
            place_name=self.place_name,
            country_code=self.country_code,
            region=self.region,
        )


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
        # One cache for both entry points; the key shapes differ (4-tuple for
        # geocode, 6-tuple for geocode_candidates) so they never collide. Values
        # are `GeocodeResult | None` or `list[GeocodeCandidate]` per key shape.
        self._cache: OrderedDict[tuple, Any] = OrderedDict()

    # --- limit=1 convenience (unchanged behaviour) ------------------------------------------
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
        params: dict[str, str | int] = {
            "q": query,
            "types": types,
            "limit": 1,
            "language": language or "en",
            "access_token": self._token,
        }
        if country:
            params["country"] = country.lower()
        data = self._request(params)
        result = self._parse_one(data, fallback=query) if data is not None else None
        self._remember(key, result)
        return result

    # --- multi-candidate (S-G3) -------------------------------------------------------------
    def geocode_candidates(
        self,
        query: str,
        *,
        country: str | None = None,
        language: str | None = None,
        proximity: str | None = None,
        types: str = CANDIDATE_TYPES,
        limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> list[GeocodeCandidate]:
        """Return up to `limit` parsed candidates (never raises).

        `proximity` is a Mapbox soft ranking bias — a `"lon,lat"` string (the
        user's GPS) or the literal `"ip"`; it never filters. `country` is the
        ONLY hard filter here (an explicit user-named country). `language` biases
        Mapbox's own scoring AND localises the returned text (probed: pt → Lisboa
        preferred). An empty list means a transient failure or a genuine no-match
        — the caller degrades honestly.
        """
        key = (query, country, language, proximity, types, limit)
        if key in self._cache:
            self._cache.move_to_end(key)
            return list(self._cache[key])
        params: dict[str, str | int] = {
            "q": query,
            "types": types,
            "limit": limit,
            # One-shot complete query (the LLM hands us a full destination string,
            # not keystrokes) — autocomplete off sharpens ranking (geo memo §A.1).
            "autocomplete": "false",
            "access_token": self._token,
        }
        if language:
            params["language"] = language
        if country:
            params["country"] = country.lower()
        if proximity:
            params["proximity"] = proximity
        data = self._request(params)
        candidates = self._parse_candidates(data) if data is not None else []
        self._remember(key, candidates)
        return list(candidates)

    def containing_area_ids(self, latitude: float, longitude: float) -> set[str] | None:
        """Provider administrative membership; None means verification unavailable.

        A bounding box/circle is retrieval geometry, never membership proof.
        Match provider IDs, including alternate administrative levels, rather
        than translated labels or postal-code prefixes.
        """
        key = ("reverse", latitude, longitude)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        data = self._request({
            "latitude": str(latitude), "longitude": str(longitude),
            "types": "region,district,place,locality,neighborhood", "access_token": self._token,
        }, reverse=True)
        if data is None:
            return None  # do not cache transient verification failures
        ids: set[str] = set()

        def collect(value: object) -> None:
            if not isinstance(value, dict):
                return
            identifier = value.get("mapbox_id")
            if isinstance(identifier, str) and identifier:
                ids.add(identifier)
            wikidata = value.get("wikidata_id")
            if isinstance(wikidata, str) and wikidata.startswith("Q") and wikidata[1:].isascii() and wikidata[1:].isdigit():
                ids.add("wikidata:" + wikidata)
            for item in value.values():
                if isinstance(item, dict):
                    collect(item)

        for feature in data.get("features") or []:
            collect(feature.get("properties"))
        self._remember(key, ids)
        return ids

    # --- shared HTTP + parsing --------------------------------------------------------------
    def _remember(self, key: tuple, value: object) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_maxsize:
            self._cache.popitem(last=False)

    def _request(self, params: dict[str, str | int], *, reverse: bool = False) -> dict | None:
        """1 initial call + 1 retry, each bounded by the timeout. Returns the
        parsed JSON, or None on a failure that survived the retry."""
        attempts = 2
        for attempt in range(attempts):
            try:
                endpoint = GEOCODE_URL.replace("/forward", "/reverse") if reverse else GEOCODE_URL
                response = self._client.get(endpoint, params=params, timeout=self._timeout)
                response.raise_for_status()
            except httpx.HTTPError:
                if attempt == attempts - 1:
                    mark_level("ERROR", status_message="mapbox_retry_exhausted")
                    return None
                continue
            return response.json()
        return None

    @staticmethod
    def _coords(feature: dict, props: dict) -> tuple[float, float] | None:
        """(lat, lon) from a v6 feature — geometry first (existing behaviour),
        then `properties.coordinates` (both present live)."""
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) >= 2:
            return float(coords[1]), float(coords[0])
        pc = props.get("coordinates") or {}
        if pc.get("latitude") is not None and pc.get("longitude") is not None:
            return float(pc["latitude"]), float(pc["longitude"])
        return None

    @staticmethod
    def _provider_place_name(props: dict) -> str:
        # Localized full_address may use another script than the provider's
        # canonical name. Both are evidence from the same feature; retain them
        # so name validation does not require an invented translation/alias.
        name = str(props.get("name") or "").strip()
        address = str(props.get("full_address") or "").strip()
        if name and address and name.casefold() not in address.casefold():
            return f"{name}, {address}"
        return address or name

    @classmethod
    def _parse_one(cls, data: dict, *, fallback: str) -> GeocodeResult | None:
        features = data.get("features") or []
        if not features:
            return None
        feature = features[0]
        props = feature.get("properties") or {}
        latlon = cls._coords(feature, props)
        if latlon is None:
            return None
        lat, lng = latlon
        context = props.get("context") or {}
        country_ctx = context.get("country") or {}
        region_ctx = context.get("region") or {}
        return GeocodeResult(
            latitude=lat,
            longitude=lng,
            place_name=cls._provider_place_name(props) or fallback,
            country_code=str(country_ctx.get("country_code") or "").upper(),
            region=str(region_ctx.get("region_code") or region_ctx.get("name") or ""),
        )

    @classmethod
    def _parse_candidates(cls, data: dict) -> list[GeocodeCandidate]:
        out: list[GeocodeCandidate] = []
        for rank, feature in enumerate(data.get("features") or []):
            props = feature.get("properties") or {}
            latlon = cls._coords(feature, props)
            if latlon is None:
                continue
            lat, lng = latlon
            context = props.get("context") or {}
            country_ctx = context.get("country") or {}
            region_ctx = context.get("region") or {}
            raw_bbox = props.get("bbox") or feature.get("bbox")
            bbox: tuple[float, float, float, float] | None = None
            if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
                bbox = (float(raw_bbox[0]), float(raw_bbox[1]), float(raw_bbox[2]), float(raw_bbox[3]))
            name = str(props.get("name") or "")
            out.append(
                GeocodeCandidate(
                    latitude=lat,
                    longitude=lng,
                    name=name,
                    place_name=cls._provider_place_name(props),
                    place_formatted=str(props.get("place_formatted") or props.get("full_address") or name),
                    feature_type=str(props.get("feature_type") or ""),
                    country_code=str(country_ctx.get("country_code") or "").upper(),
                    region=str(region_ctx.get("name") or region_ctx.get("region_code") or ""),
                    bbox=bbox,
                    rank=rank,
                    mapbox_id=str(props.get("mapbox_id") or ""),
                    administrative_code=str(region_ctx.get("region_code") or ""),
                    parent_ids=tuple(sorted({
                        str(value["mapbox_id"])
                        for key, value in context.items()
                        if key != props.get("feature_type") and isinstance(value, dict) and value.get("mapbox_id")
                    })),
                    wikidata_id=str(props.get("wikidata_id") or
                                    (context.get(props.get("feature_type")) or {}).get("wikidata_id") or ""),
                )
            )
        return out
