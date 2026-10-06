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

⚠️ `proximity` (2026-08-26). Mapbox documents, for this endpoint: *"If not
provided, the default is IP proximity."* So NOT sending one is not "no bias" —
it is "bias by whatever IP this process happens to egress from". That is how a
prod turn for "autour des champs élysées" resolved to a shop of that name in
Toulon, 830 km away, while the same arguments replayed from a laptop returned
Paris. This client cannot fix that (Mapbox offers no way to switch the bias
off); it only makes it survivable by returning the FULL candidate list, so the
caller's deterministic ranker gets to decide instead of Mapbox's top-1. The
real fix lives in `geocode_tool`: put the city in the query.
"""
from __future__ import annotations

from collections import OrderedDict

import httpx

from hotel_search_agent.mapbox_client import GeocodeCandidate, GeocodeResult

SEARCHBOX_URL = "https://api.mapbox.com/search/searchbox/v1/forward"

# POIs and named zones only — this tier exists precisely for what v6 can't do.
DEFAULT_TYPES = "poi,address,neighborhood,locality,place"

#: Mapbox's documented maximum for this endpoint. We ask for all of them: the
#: extra candidates cost nothing (same call, same SKU) and they are the only
#: material the caller's ranker has to overrule an IP-biased top-1.
MAX_LIMIT = 10


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
        self._cache: OrderedDict[tuple, list[GeocodeCandidate]] = OrderedDict()

    def forward(
        self,
        query: str,
        *,
        country: str | None = None,
        language: str | None = None,
        proximity: str | None = None,
        types: str = DEFAULT_TYPES,
    ) -> GeocodeResult | None:
        """Mapbox's OWN best POI/landmark match for `query`, or None (transient
        failure or no match).

        Kept as-is for callers that genuinely want the vendor's top-1, but note
        that top-1 is IP-biased (module docstring): prefer
        `forward_candidates` + a deterministic ranker for anything that decides
        where a customer's search happens."""
        candidates = self.forward_candidates(
            query, country=country, language=language, proximity=proximity,
            types=types, limit=1,
        )
        return candidates[0].as_result() if candidates else None

    def forward_candidates(
        self,
        query: str,
        *,
        country: str | None = None,
        language: str | None = None,
        proximity: str | None = None,
        types: str = DEFAULT_TYPES,
        limit: int = MAX_LIMIT,
    ) -> list[GeocodeCandidate]:
        """Every candidate Mapbox returned for `query`, in its own rank order.

        Same single call and same SKU as the old `limit=1` version — the extra
        candidates are free, and they are what lets `geo_resolver.rank_landmark`
        overrule an IP-biased top-1. An empty list means a transient failure OR
        no match; the caller degrades honestly either way (it cannot tell them
        apart, and never should invent a coordinate)."""
        key = (query, country, language, proximity, types, limit)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        params: dict[str, str | int] = {
            "q": query,
            "types": types,
            "limit": max(1, min(limit, MAX_LIMIT)),
            "access_token": self._token,
        }
        if country:
            params["country"] = country.lower()
        if language:
            params["language"] = language
        if proximity:
            params["proximity"] = proximity
        candidates = self._forward_with_retry(params, fallback=query)
        self._remember(key, candidates)
        return candidates

    def _remember(self, key: tuple, value: list[GeocodeCandidate]) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_maxsize:
            self._cache.popitem(last=False)

    def _forward_with_retry(
        self, params: dict[str, str | int], *, fallback: str
    ) -> list[GeocodeCandidate]:
        attempts = 2
        for attempt in range(attempts):
            try:
                response = self._client.get(SEARCHBOX_URL, params=params, timeout=self._timeout)
                response.raise_for_status()
            except httpx.HTTPError:
                if attempt == attempts - 1:
                    return []
                continue
            return self._parse(response.json(), fallback=fallback)
        return []

    @staticmethod
    def _parse(data: dict, *, fallback: str) -> list[GeocodeCandidate]:
        candidates: list[GeocodeCandidate] = []
        for rank, feature in enumerate(data.get("features") or []):
            props = feature.get("properties") or {}
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            if len(coords) >= 2:
                lat, lng = float(coords[1]), float(coords[0])
            else:
                pc = props.get("coordinates") or {}
                if pc.get("latitude") is None or pc.get("longitude") is None:
                    continue
                lat, lng = float(pc["latitude"]), float(pc["longitude"])
            context = props.get("context") or {}
            country_ctx = context.get("country") or {}
            region_ctx = context.get("region") or {}
            # A POI's `full_address` is its CONTAINING commune ("92800 Puteaux,
            # France" for "La Défense") — it doesn't echo the landmark the user
            # named. Prefix the POI name so the SAME echo-back guard the caller
            # runs on a tier-1 result validates this one ("La Défense" must
            # appear in place_name).
            name = str(props.get("name") or "")
            full_address = str(props.get("full_address") or "")
            if name and full_address and name.lower() not in full_address.lower():
                place_name = f"{name}, {full_address}"
            else:
                place_name = full_address or name or fallback
            candidates.append(
                GeocodeCandidate(
                    latitude=lat,
                    longitude=lng,
                    name=name or fallback,
                    place_name=place_name,
                    place_formatted=str(props.get("place_formatted") or full_address),
                    feature_type=str(props.get("feature_type") or "poi"),
                    country_code=str(country_ctx.get("country_code") or "").upper(),
                    region=str(region_ctx.get("name") or region_ctx.get("region_code") or ""),
                    bbox=None,
                    rank=rank,
                    iata_code=SearchBoxClient._iata_code(props),
                    provider_place_id=props.get("mapbox_id") or feature.get("id"),
                )
            )
        return candidates

    @staticmethod
    def _iata_code(props: dict) -> str | None:
        value = (props.get("external_ids") or {}).get("iata")
        if isinstance(value, str) and len(value) == 3 and value.isascii() and value.isalpha():
            return value.upper()
        return None
