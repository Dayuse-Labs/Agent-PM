"""The starting point of a search (point 4, review of the 97 real conversations
after #173, and the agent-usa / AgentB2C side-by-side of 2026-10-29).

Each case is a `GeoIntent` the leaf's model really sent (Langfuse traces of
2026-10-28/29) and the answers Mapbox v6 and Search Box really give for it,
recorded live on 2026-10-29 (`tests/fixtures/mapbox_v6/`,
`tests/fixtures/searchbox/`; the parsing is the clients' own). The inventory
is the committed snapshot (`inventory_snapshot.json`), as in production.

- « Milano », « brooklyn », « palm springs » asked the user which one: a
  hamlet near Treviso, Brooklyn (Maryland), a neighbourhood of Hialeah.
- « Mantova » resolved to « Cascina Mantova », a farmstead near Monza.
- « New York » searched around City Hall: Jersey City and Brooklyn cards.
- « a hotel near Times Square »: « I couldn't locate Times Square ».
- « Ostia lido » four times: four searches on the centre of Rome, unsaid.
- « 53088 » then « try a nearby area »: Stockbridge, Wisconsin, then Georgia.
- « going north » around a device fix in California: North, Lebanon.
- A geocoder timeout was cached as « no match ».
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types as genai_types

from b2c_common.geo_intent import CityRef, GeoIntent, Place
from hotel_search_agent import geo_resolver, geocode_tool
from hotel_search_agent.geocode_tool import geocode_location
from hotel_search_agent.inventory import get_inventory, haversine_km
from hotel_search_agent.mapbox_client import GeocodeCandidate, MapboxClient
from hotel_search_agent.searchbox_client import SearchBoxClient

FIXTURES = Path(__file__).parent / "fixtures"
AREA_TYPES = "region,district"
POSTCODE_TYPES = "postcode"


def _v6(name: str) -> list[GeocodeCandidate]:
    return MapboxClient._parse_candidates(json.loads((FIXTURES / "mapbox_v6" / name).read_text()))


def _box(name: str, query: str) -> list[GeocodeCandidate]:
    return SearchBoxClient._parse(json.loads((FIXTURES / "searchbox" / name).read_text()), fallback=query)


class _V6:
    """Mapbox v6, answering per (query, country) — per (query, country, types)
    for the area and postcode lookups."""

    def __init__(self, answers: dict[tuple, list[GeocodeCandidate]]):
        self.answers = answers
        self.calls: list[tuple] = []

    def geocode_candidates(self, query, *, country=None, language=None, proximity=None,
                           types=None, **kwargs):
        key = (query, (country or "").upper() or None)
        self.calls.append((query, key[1], types))
        if types in (AREA_TYPES, POSTCODE_TYPES):
            return list(self.answers.get((*key, types), []))
        return list(self.answers.get(key, []))


class _SearchBox:
    def __init__(self, answers: dict[tuple, list[GeocodeCandidate]] | None = None):
        self.answers = answers or {}
        self.calls: list[tuple] = []

    def forward_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, country, proximity))
        return list(self.answers.get((query, (country or "").upper() or None), []))


@pytest.fixture
def geo(monkeypatch):
    def patch(v6: dict, box: dict | None = None):
        fake_v6, fake_box = _V6(v6), _SearchBox(box)
        monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: fake_v6)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: fake_box)
        return fake_v6, fake_box
    return patch


def _ctx(*texts, profile_in=None):
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in or {}})
    )
    parts = [genai_types.Part(text=t) for t in texts]
    parts.append(convert_a2a_part_to_genai_part(datapart))
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


def _city(mention: str, canonical: str, country: str) -> GeoIntent:
    return GeoIntent(
        places=[Place(mention=mention, kind="city", canonical=canonical, country=country)],
        city=CityRef(mention=mention, canonical=canonical, country=country),
        relation="whole_city", carryover="new",
    )


def _km(result: dict, lat: float, lon: float) -> float:
    return haversine_km(result["latitude"], result["longitude"], lat, lon)


# --- 1. A homonym far smaller than the city asked for is not a question -------


class TestTheCityOutweighsItsHamlets:
    def test_milano_is_not_asked_against_a_hamlet_near_treviso(self, geo):
        # Prod trace 669615d6 (S039): city {mention « Milano », canonical
        # « Milan »} → « Milano (città metropolitana) o Milan (Zero Branco) ? ».
        geo({("Milan", "IT"): _v6("place_milan_it.json")})

        result = geocode_location(
            intent=GeoIntent(city=CityRef(mention="Milano", canonical="Milan", country="IT"),
                             relation="whole_city", carryover="new"),
            tool_context=_ctx("Milano il 13 e 14 notte"),
        )

        assert result["ok"] is True
        assert result["resolved_place"] == "Milano, città metropolitana di Milano, Italia"

    def test_the_next_turn_carries_milano_and_asks_nothing(self, geo):
        # Replay of S039: the name carried was the model's canonical « Milan »,
        # and « Vorrei jacuzzi » asked the hamlet question again.
        geo({("Milan", "IT"): _v6("place_milan_it.json"), ("Milano", "IT"): _v6("place_milano_it.json")})

        first = geocode_location(
            intent=GeoIntent(city=CityRef(mention="Milano", canonical="Milan", country="IT"),
                             relation="whole_city", carryover="new"),
            tool_context=_ctx("Milano il 13 e 14 notte"),
        )
        assert first["profile_delta"]["last_city"] == "Milano"

        second = geocode_location(
            intent=GeoIntent(carryover="keep"),
            profile_location_hint="Milano",
            tool_context=_ctx("Vorrei jacuzzi o vasca idromassaggio",
                              profile_in={"city": "Milano", "country_anchor": "IT"}),
        )
        assert second["ok"] is True
        assert second["resolved_place"] == "Milano, città metropolitana di Milano, Italia"

    def test_brooklyn_is_new_york_not_maryland(self, geo):
        # Prod trace c602a62c (S076): « brooklyn » → Maryland or New York ?
        geo({("Brooklyn", "US"): _v6("place_brooklyn_us.json")})

        result = geocode_location(
            intent=GeoIntent(
                places=[Place(mention="brooklyn", kind="city", canonical="Brooklyn",
                              city="New York", country="US", city_inferred=True)],
                city=CityRef(mention="", canonical="New York", country="US"),
                relation="whole_city", carryover="new",
            ),
            tool_context=_ctx("brooklyn"),
        )

        assert result["ok"] is True
        assert result["resolved_place"] == "Brooklyn, New York, United States"

    def test_palm_springs_is_the_californian_city_not_a_neighbourhood_of_hialeah(self, geo):
        # Prod trace c3c67b2e (S077): « Daypass palm springs ».
        geo({("Palm Springs", "US"): _v6("place_palm_springs_us.json")})

        result = geocode_location(
            intent=_city("palm springs", "Palm Springs", "US"),
            tool_context=_ctx("Daypass palm springs"),
        )

        assert result["ok"] is True
        assert result["resolved_place"] == "Palm Springs, California, United States"

    def test_mantova_is_the_city_not_a_farmstead_near_monza(self, geo):
        # Prod traces b730b0a7 / 479d264b (S022, S024): « Cascina Mantova,
        # Biassono », 114 hotels around it (Milan's) against Mantova's 2.
        geo({("Mantova", "IT"): _v6("place_mantova_it.json")})

        result = geocode_location(intent=_city("Mantova", "Mantova", "IT"), tool_context=_ctx("Mantova"))

        assert result["ok"] is True
        assert result["resolved_place"] == "Mantova, provincia di Mantova, Italia"

    def test_two_homonyms_of_a_kind_are_still_a_question(self):
        # The rule removes a candidate only a far bigger exact-name city
        # outweighs: two comparable towns (Springfield-like) keep the question.
        def town(region, lat, lon, half):
            return GeocodeCandidate(
                latitude=lat, longitude=lon, name="Springfield",
                place_name=f"Springfield, {region}, United States", place_formatted=f"{region}, United States",
                feature_type="place", country_code="US", region=region,
                bbox=(lon - half, lat - half, lon + half, lat + half), rank=0,
            )

        class Inventory:
            def count_near(self, lat, lon, *, radius_km=25.0):
                return 12

        resolution = geo_resolver.resolve(
            [town("Illinois", 39.80, -89.65, 0.08), town("Missouri", 37.21, -93.29, 0.10)],
            inventory=Inventory(), requested_name="Springfield", locale_country="US",
        )

        assert resolution.decision == "clarify"

    def test_a_homonym_without_hotels_never_outweighs_one_with_them(self):
        # Saint-Denis (La Réunion) covers 12 times the 93's: the 93 has hotels.
        def saint_denis(region, lat, lon, half_lat, half_lon):
            return GeocodeCandidate(
                latitude=lat, longitude=lon, name="Saint-Denis",
                place_name=f"Saint-Denis, {region}, France", place_formatted=f"{region}, France",
                feature_type="place", country_code="FR", region=region,
                bbox=(lon - half_lon, lat - half_lat, lon + half_lon, lat + half_lat), rank=0,
            )

        paris_93 = saint_denis("Seine-Saint-Denis", 48.936, 2.357, 0.016, 0.024)
        reunion = saint_denis("La Réunion", -20.879, 55.448, 0.06, 0.07)

        class Inventory:
            def count_near(self, lat, lon, *, radius_km=25.0):
                return 300 if lat > 0 else 1

        resolution = geo_resolver.resolve(
            [reunion, paris_93], inventory=Inventory(), requested_name="Saint-Denis",
        )

        assert resolution.chosen is paris_93


# --- 2. A city search starts where the city's hotels are --------------------


class TestTheCityStartsWhereItsHotelsAre:
    def test_new_york_is_searched_from_midtown_not_from_city_hall(self, geo):
        # Side-by-side 2026-10-29: cards in Jersey City and Brooklyn, 5.5-6.5 km
        # from Bryant Park, because Mapbox puts New York City at City Hall.
        geo({("New York, New York", "US"): _v6("place_new_york_us.json")})

        result = geocode_location(
            intent=_city("New York", "New York", "US"), tool_context=_ctx("hotel in New York tomorrow afternoon"),
        )

        assert result["ok"] is True
        assert result["resolved_place"] == "New York City, New York, United States"
        assert _km(result, 40.7549, -73.9840) < 1.0  # Bryant Park
        assert _km(result, 40.7127, -74.0060) > 4.0  # City Hall

    def test_paris_keeps_the_geocoders_point(self, geo):
        geo({("Paris", "FR"): _v6("place_paris_fr.json")})

        result = geocode_location(intent=_city("Paris", "Paris", "FR"), tool_context=_ctx("un hôtel à Paris demain"))

        assert result["ok"] is True
        assert (result["latitude"], result["longitude"]) == (48.853495, 2.348392)

    def test_the_centre_moves_only_where_the_hotels_clearly_are(self):
        inventory = get_inventory()
        moved = {
            name: inventory.dense_centre(lat, lon)
            for name, (lat, lon) in {
                "New York": (40.7127, -74.006), "Paris": (48.8535, 2.3484), "London": (51.5073, -0.1276),
                "Rome": (41.9, 12.4767), "Milan": (45.4639, 9.1886), "Madrid": (40.4213, -3.7012),
                "Los Angeles": (34.0481, -118.2542), "Singapore": (1.3516, 103.8081),
            }.items()
        }

        assert {name for name, point in moved.items() if point} == {"New York", "Singapore"}


# --- 3. A landmark Mapbox knows as a neighbourhood --------------------------


def test_times_square_is_found_and_searched_around(geo):
    # Side-by-side 2026-10-29: « I couldn't locate "Times Square": here are
    # hotels in New York ». Search Box has the neighbourhood, with no
    # `full_address`: named alone, it failed the echo of the state (New York).
    geo(
        {("Times Square, New York", "US"): _v6("place_times_square_new_york_us.json"),
         ("New York", "US"): _v6("place_new_york_us.json")},
        {("Times Square", "US"): _box("times_square_us_nyc.json", "Times Square")},
    )

    result = geocode_location(
        intent=GeoIntent(
            places=[Place(mention="Times Square", kind="landmark", canonical="Times Square",
                          city="New York", country="US", city_inferred=True)],
            relation="near", carryover="new",
        ),
        tool_context=_ctx("a hotel near Times Square tomorrow"),
    )

    assert result["ok"] is True
    assert "landmark_unresolved" not in result
    assert _km(result, 40.758, -73.9855) < 0.5
    assert result["distance_origin_type"] == "poi"


def test_a_search_box_neighbourhood_carries_its_context_in_its_name():
    times_square = _box("times_square_us_nyc.json", "Times Square")[0]

    assert times_square.feature_type == "neighborhood"
    assert times_square.place_name == "Times Square, Manhattan, New York, United States"


# --- 4. A district known only by the places named after it -------------------


OSTIA = GeoIntent(
    places=[Place(mention="Ostia lido", kind="neighborhood", canonical="Lido di Ostia",
                  city="Rome", country="IT", city_inferred=True)],
    relation="in", carryover="new",
)


def test_ostia_lido_is_searched_where_its_namesakes_stand(geo):
    # Prod session 4919ffbc (S041): « Ostia lido » repeated four times, four
    # searches on the centre of Rome, 25 km away.
    geo(
        {("Lido di Ostia, Rome", "IT"): _v6("place_lido_di_ostia_rome_it.json")},
        {("Lido di Ostia", "IT"): _box("lido_di_ostia_it_rome.json", "Lido di Ostia")},
    )

    result = geocode_location(intent=OSTIA, tool_context=_ctx("Ostia lido"))

    assert result["ok"] is True
    assert _km(result, 41.732, 12.281) < 1.5  # Ostia Lido, its seafront
    assert _km(result, 41.9, 12.4767) > 20.0  # not the centre of Rome
    assert result["profile_delta"]["zone"] == "Lido di Ostia"


def test_without_namesakes_together_the_city_is_searched_and_it_is_said(geo):
    # One business only: no district to locate. The centre of Rome is
    # searched, as before, but the reply now says the spot was not found.
    one_business = _box("lido_di_ostia_it_rome.json", "Lido di Ostia")[:1]
    geo(
        {("Lido di Ostia, Rome", "IT"): _v6("place_lido_di_ostia_rome_it.json"),
         ("Rome", "IT"): [c for c in _v6("place_lido_di_ostia_rome_it.json") if c.name == "Roma"]},
        {("Lido di Ostia", "IT"): one_business},
    )

    result = geocode_location(intent=OSTIA, tool_context=_ctx("Ostia lido"))

    assert result["ok"] is True
    assert result["landmark_unresolved"] == "Lido di Ostia"
    assert result["resolved_place"].startswith("Roma")


# --- 5. The state of the place found travels with its name -------------------


def test_stockbridge_wisconsin_stays_in_wisconsin_on_the_next_turn(geo):
    # Prod session 12665ef3 (S096): « 53088 » → Stockbridge, Wisconsin; then
    # « try a nearby area » re-geocoded the bare name → Stockbridge, Georgia.
    stockbridge = _v6("place_stockbridge_us.json")
    wisconsin_first = sorted(stockbridge, key=lambda c: c.region != "Wisconsin")
    geo({
        ("53088", None, POSTCODE_TYPES): _v6("postcode_53088.json"),
        ("Stockbridge, Wisconsin", "US"): wisconsin_first,
        ("Stockbridge", "US"): stockbridge,
    })

    first = geocode_location(
        intent=GeoIntent(places=[Place(mention="53088", kind="address", canonical="53088",
                                       postal_code="53088")], relation="near", carryover="new"),
        tool_context=_ctx("53088", profile_in={"entry_market_country": "US"}),
    )
    assert first["ok"] is True
    assert first["profile_delta"]["last_state_context"] == "WI"

    second = geocode_location(
        intent=GeoIntent(relation="in", carryover="keep"),
        profile_state_context="WI",
        profile_location_hint="Stockbridge",
        tool_context=_ctx("try a nearby area", profile_in={
            "city": "Stockbridge", "country_anchor": "US", "state_anchor": "WI",
            "entry_market_country": "US",
        }),
    )

    assert second["ok"] is True
    assert second["resolved_place"] == "Stockbridge, Wisconsin, United States"


# --- 6. An area nobody placed in a country stays in the market's -------------


def test_north_is_not_looked_up_in_lebanon(geo):
    # Prod trace 66eb789b (S066): « going north », a region with no country.
    lebanon = GeocodeCandidate(
        latitude=34.437362, longitude=35.834855, name="North", place_name="North, Lebanon",
        place_formatted="Lebanon", feature_type="region", country_code="LB", region="North",
        bbox=None, rank=0,
    )
    v6, box = geo({("north", None, AREA_TYPES): [lebanon]})

    result = geocode_location(
        intent=GeoIntent(places=[Place(mention="north", kind="region", canonical="north")],
                         relation="in", carryover="new"),
        tool_context=_ctx("How about 30th of this month going north",
                          profile_in={"entry_market_country": "US"}),
    )

    assert result.get("ok") is not True
    assert ("north", None, AREA_TYPES) not in v6.calls
    assert box.calls and all(country == "US" for _q, country, _p in box.calls)


# --- 7. A city asked of Search Box ranks a town above a business --------------


def test_a_city_asked_of_search_box_prefers_the_town():
    business = GeocodeCandidate(
        latitude=45.16, longitude=10.80, name="Mantova", place_name="Mantova, 46100 Mantova, Italia",
        place_formatted="46100 Mantova, Italia", feature_type="poi", country_code="IT", region="",
        bbox=None, rank=0,
    )
    town = GeocodeCandidate(
        latitude=45.158, longitude=10.794, name="Mantova", place_name="Mantova, provincia di Mantova, Italia",
        place_formatted="provincia di Mantova, Italia", feature_type="place", country_code="IT",
        region="provincia di Mantova", bbox=None, rank=1,
    )

    class Inventory:
        def count_near(self, lat, lon, *, radius_km=25.0):
            return 2

    picked = geo_resolver.rank_landmark(
        [business, town], requested_zone="Mantova", inventory=Inventory(), city_query=True,
    )

    assert picked is town


# --- 8. A geocoder failure is not « no match » --------------------------------


class TestAFailureIsNeverCached:
    def test_mapbox_asks_again_after_a_timeout(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] <= 2:
                raise httpx.ReadTimeout("slow", request=request)
            return httpx.Response(200, json=json.loads((FIXTURES / "mapbox_v6" / "place_mantova_it.json").read_text()))

        client = MapboxClient("tok", client=httpx.Client(transport=httpx.MockTransport(handler)))

        assert client.geocode_candidates("Mantova", country="IT") == []  # 2 attempts, both failed
        again = client.geocode_candidates("Mantova", country="IT")

        assert calls["n"] == 3
        assert again and again[0].name == "Mantova"

    def test_mapbox_still_caches_a_real_no_match(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

        client = MapboxClient("tok", client=httpx.Client(transport=httpx.MockTransport(handler)))
        client.geocode_candidates("Nowhere")
        client.geocode_candidates("Nowhere")

        assert calls["n"] == 1

    def test_search_box_asks_again_after_a_timeout(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] <= 2:
                raise httpx.ReadTimeout("slow", request=request)
            return httpx.Response(200, json=json.loads((FIXTURES / "searchbox" / "times_square_us_nyc.json").read_text()))

        client = SearchBoxClient("tok", client=httpx.Client(transport=httpx.MockTransport(handler)))

        assert client.forward_candidates("Times Square", country="US") == []
        again = client.forward_candidates("Times Square", country="US")

        assert calls["n"] == 3
        assert again and again[0].name == "Times Square"
