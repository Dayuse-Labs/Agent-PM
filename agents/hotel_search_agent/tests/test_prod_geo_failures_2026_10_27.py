"""Prod 2026-10-26/27 (128 real conversations after the switch of ai.dayuse.com):
the geocoding failures the user read as a search outage, and the areas that
looped on « which city? ».

Each case is a `GeoIntent` the leaf's model really sent (Langfuse traces, tool
input) and the candidate lists Mapbox really returns for it: probed live on
2026-10-27, plus the namesake the production container (an EU datacenter, IP
biased) got first. Inventory counts are the snapshot's own (25 km).

A. `geocode_echo_mismatch` (8 traces): the echo guard rightly refused a
   namesake (Galveston -> Alveston GB, Ojai -> Oost NL, Cuneo -> Luneo,
   Salzburg -> Sulzburg DE, Mechelen -> its own French name), and the turn
   then ended on "I can't reach the hotel search right now".
B. an administrative area (« le 06 », « l'Hérault », « Puglia ») reached the
   zone-without-city question, again and again.

Offline: Mapbox, Search Box and the inventory are fakes answering per
(query, country), as the real APIs do.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import (
    convert_a2a_part_to_genai_part,
    convert_genai_part_to_a2a_part,
)
from google.genai import types as genai_types

from b2c_common.clarification import Clarification
from b2c_common.geo_intent import CityRef, GeoIntent, Place
from hotel_search_agent import geocode_tool
from hotel_search_agent.geocode_tool import geocode_location
from hotel_search_agent.mapbox_client import GeocodeCandidate
from hotel_search_agent.response_bridge import capture_after_tool, emit_search_datapart


def _c(name, place_name, cc, region, *, ftype="place", rank=0, lat=0.0, lon=0.0):
    return GeocodeCandidate(
        latitude=lat, longitude=lon, name=name, place_name=place_name,
        place_formatted=place_name.split(", ", 1)[-1], feature_type=ftype,
        country_code=cc, region=region, bbox=None, rank=rank,
    )


def _ranked(*candidates: GeocodeCandidate) -> list[GeocodeCandidate]:
    return [
        GeocodeCandidate(**{**c.__dict__, "rank": i}) for i, c in enumerate(candidates)
    ]


# --- candidates (Mapbox v6, probed 2026-10-27; coordinates as returned) -------
OJAI = _c("Ojai", "Ojai, California, United States", "US", "California", lat=34.448, lon=-119.243)
OOST = _c("Oost", "Oost, Waddinxveen, South Holland, Netherlands", "NL", "South Holland",
          ftype="locality", lat=52.03, lon=4.66)
GALVESTON_TX = _c("Galveston", "Galveston, Texas, United States", "US", "Texas", lat=29.306, lon=-94.793)
GALVESTON_IN = _c("Galveston", "Galveston, Indiana, United States", "US", "Indiana", lat=40.579, lon=-86.187)
ALVESTON = _c("Alveston", "Alveston, South Gloucestershire, England, United Kingdom", "GB", "England",
              ftype="locality", lat=51.59, lon=-2.532)
CUNEO = _c("Cuneo", "Cuneo, provincia di Cuneo, Italia", "IT", "provincia di Cuneo", lat=44.389, lon=7.547)
CUNEO_SV = _c("Cuneo", "Cuneo, Balestrino, provincia di Savona, Italia", "IT", "provincia di Savona",
              ftype="locality", lat=44.126, lon=8.161)
LUNEO = _c("Luneo", "Luneo, Mirano, città metropolitana di Venezia, Italia", "IT",
           "città metropolitana di Venezia", ftype="locality", lat=45.51, lon=12.123)
SALZBURG = _c("Salzburg", "Salzburg, Salzburg, Österreich", "AT", "Salzburg", lat=47.8, lon=13.045)
SULZBURG = _c("Sulzburg", "Sulzburg, Kreis Breisgau-Hochschwarzwald, Baden-Württemberg, Deutschland",
              "DE", "Baden-Württemberg", lat=47.84, lon=7.71)
MECHELEN_NL = _c("Mechelen", "Mechelen, Limbourg, Pays-Bas", "NL", "Limbourg", lat=50.797, lon=5.926)
MALINES = _c("Mechelen", "Malines, province d'Anvers, Belgique", "BE", "province d'Anvers",
             lat=51.028, lon=4.48)
MACHELEN = _c("Machelen", "Machelen, Brabant flamand, Belgique", "BE", "Brabant flamand",
              lat=50.913, lon=4.433)
CLAYTON = _c("Clayton", "Clayton, Victoria, Australia", "AU", "Victoria", ftype="locality",
             lat=-37.914, lon=145.127)
MELBOURNE = _c("Melbourne", "Melbourne, Victoria, Australia", "AU", "Victoria", lat=-37.814, lon=144.963)
MONACO = _c("Monaco", "Monaco", "MC", "Monaco", lat=43.738, lon=7.424)
ALPES_MARITIMES = _c("Alpes-Maritimes", "Alpes-Maritimes, France", "FR", "Alpes-Maritimes",
                     ftype="region", lat=43.701, lon=7.268)
ALPES_VALENCE = _c("Alpes", "Alpes, Valence, Drôme, France", "FR", "Drôme", ftype="neighborhood",
                   lat=44.929, lon=4.899)
HERAULT = _c("Hérault", "Hérault, France", "FR", "Hérault", ftype="region", lat=43.611, lon=3.877)
PUGLIA = _c("Puglia", "Puglia, Italia", "IT", "Puglia", ftype="region", lat=41.126, lon=16.862)
LAGO_DOSSENA = _c("Lago", "Lago, Dossena, provincia di Bergamo, Italia", "IT", "provincia di Bergamo",
                  ftype="locality", lat=45.877, lon=9.688)
LAGO_COMO_POI = _c("Lago como", "Lago como, 22017 Menaggio, Italia", "IT", "", ftype="poi",
                   lat=46.022, lon=9.239)

#: Hotels within 25 km in the inventory snapshot (`inventory_snapshot.json`).
INVENTORY = {
    52.03: 33, 51.59: 18, 45.51: 30, 47.8: 2, 47.84: 0, 51.028: 74, 50.797: 6, 50.913: 60,
    -37.914: 99, -37.814: 108, 43.738: 37, 43.701: 53, 43.611: 24, 41.126: 4, 29.306: 1,
}


#: `mapbox_client.AREA_TYPES`, spelled out so this file imports on a tree
#: without it (the counter-proof against `main`).
AREA_TYPES = "region,district"


class _V6:
    """Mapbox v6: one answer per (query, country, types), the call log kept."""

    def __init__(self, answers: dict[tuple, list[GeocodeCandidate]]):
        self.answers = answers
        self.calls: list[tuple] = []

    def geocode_candidates(self, query, *, country=None, language=None, proximity=None,
                           types=None, **kwargs):
        key = (query, (country or "").upper() or None)
        self.calls.append((query, key[1], types))
        if types == AREA_TYPES:
            return list(self.answers.get((*key, "area"), []))
        return list(self.answers.get(key, []))


class _SearchBox:
    def __init__(self, answers: dict[tuple, list[GeocodeCandidate]] | None = None):
        self.answers = answers or {}
        self.calls: list[tuple] = []

    def forward_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, country))
        return list(self.answers.get((query, (country or "").upper() or None), []))


class _Inventory:
    def count_near(self, lat, lon, *, radius_km=25.0):
        return INVENTORY.get(round(lat, 3), 0)


@pytest.fixture
def geo(monkeypatch):
    def patch(v6: dict, box: dict | None = None):
        fake_v6, fake_box = _V6(v6), _SearchBox(box)
        monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: fake_v6)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: fake_box)
        monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _Inventory())
        return fake_v6, fake_box
    return patch


def _ctx(*texts, profile_in=None):
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in or {}})
    )
    parts = [genai_types.Part(text=t) for t in texts]
    parts.append(convert_a2a_part_to_genai_part(datapart))
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


def _city(mention, canonical, country) -> GeoIntent:
    """The intent the leaf's model sent for a bare city (Ojai, Galveston...)."""
    return GeoIntent(
        places=[Place(mention=mention, kind="city", canonical=canonical, country=country)],
        city=CityRef(mention=mention, canonical=canonical, country=country),
        relation="whole_city", carryover="new",
    )


def _through_the_leaf(result: dict) -> tuple[dict, str]:
    """The tool response as the concierge receives it: (DataPart, text)."""
    ctx = SimpleNamespace(state={}, user_content=None)
    capture_after_tool(SimpleNamespace(name="geocode_location"), {}, ctx, result)
    content = emit_search_datapart(ctx)
    assert content is not None
    data = None
    for part in content.parts:
        if part.inline_data is not None:
            data = convert_genai_part_to_a2a_part(part).root.data
    return data or {}, "".join(p.text for p in content.parts if p.text)


# --- A1: the country the model knows scopes the lookup -------------------------


class TestTheCountryScopesTheLookup:
    def test_ojai_is_found_in_the_us_not_in_the_netherlands(self, geo):
        # Prod trace 192650c0: unscoped, the EU container got Oost (NL) first.
        v6, _ = geo({("Ojai", None): [OOST], ("Ojai", "US"): [OJAI]})

        result = geocode_location(intent=_city("Ojai", "Ojai", "US"), tool_context=_ctx("Ojai"))

        assert result["ok"] is True
        assert result["resolved_place"] == "Ojai, California, United States"
        assert v6.calls[0][:2] == ("Ojai", "US")

    def test_salzburg_in_austria(self, geo):
        geo({("Salzburg", None): [SULZBURG], ("Salzburg", "AT"): [SALZBURG]})

        result = geocode_location(
            intent=_city("Salzburg", "Salzburg", "AT"),
            tool_context=_ctx("In der Nähe Salzburg oder Linz"),
        )

        assert result["ok"] is True
        assert result["country_code"] == "AT"

    def test_a_wrong_guess_costs_one_call_never_the_place(self, geo):
        # Negative control of the scope: nothing in the guessed country echoes
        # the request, so the lookup runs again worldwide — the guess is a
        # scope, not a filter (only a NAMED country filters).
        v6, _ = geo({("Ojai", "FR"): [], ("Ojai", None): [OJAI]})

        result = geocode_location(intent=_city("Ojai", "Ojai", "FR"), tool_context=_ctx("Ojai"))

        assert result["ok"] is True
        assert [c[:2] for c in v6.calls] == [("Ojai", "FR"), ("Ojai", None)]

    def test_a_named_country_stays_the_only_filter(self, geo):
        v6, _ = geo({("Ojai", "US"): []})
        intent = GeoIntent(places=[Place(mention="Ojai", kind="city", canonical="Ojai")],
                           country_named="US")

        result = geocode_location(intent=intent, tool_context=_ctx("Ojai in the US"))

        assert result["ok"] is False
        assert all(country == "US" for _, country, _ in v6.calls)


class TestOnlyWhatEchoesIsRanked:
    def test_cuneo_is_not_traded_for_luneo_and_its_hotels(self, geo):
        # Prod trace b3a202a9: Luneo (Venice, 30 hotels) outranked Cuneo (0)
        # on inventory, then the echo guard refused it. Same country here: the
        # scope alone does not save it, the echo filter does.
        geo({("Cuneo", "IT"): _ranked(CUNEO, CUNEO_SV, LUNEO)})

        result = geocode_location(intent=_city("Cuneo", "Cuneo", "IT"), tool_context=_ctx("Cuneo"))

        assert result["ok"] is True
        assert result["resolved_place"] == "Cuneo, provincia di Cuneo, Italia"

    def test_galveston_is_asked_between_its_real_homonyms_never_alveston(self, geo):
        # Prod trace 3dcf1831: Alveston (GB, 18 hotels) was chosen and refused.
        # Scoped to the US, only real Galvestons remain; with no inventory
        # around either, the resolver's rule for a genuine near-tie applies.
        geo({
            ("Galveston", None): _ranked(GALVESTON_TX, GALVESTON_IN, ALVESTON),
            ("Galveston", "US"): _ranked(GALVESTON_TX, GALVESTON_IN),
        })

        result = geocode_location(
            intent=_city("Galveston", "Galveston", "US"), tool_context=_ctx("Galveston")
        )

        assert result["error"] == "geocode_ambiguous"
        assert result["clarification"]["kind"] == "homonym"
        labels = [o["label"] for o in result["clarification"]["options"]]
        assert labels and all("Galveston" in label for label in labels)
        assert "Alveston" not in str(result)


class TestTheUsersOwnNameIsAnEcho:
    def test_malines_is_mechelen(self, geo):
        # Prod trace ff012c60 (locale fr): canonical « Mechelen » looked up,
        # Mapbox answered « Malines, province d'Anvers, Belgique » — the very
        # place, under the user's own word — and the echo guard refused it.
        geo({
            ("Mechelen", None): _ranked(MECHELEN_NL, MALINES, MACHELEN),
            ("Mechelen", "BE"): _ranked(MALINES, MACHELEN),
        })
        intent = GeoIntent(places=[
            Place(mention="Malines", kind="city", canonical="Mechelen", country="BE"),
            Place(mention="Anvers", kind="city", canonical="Antwerp", country="BE"),
        ])

        result = geocode_location(intent=intent, locale="fr", tool_context=_ctx("Malines, Anvers"))

        assert result["ok"] is True
        assert result["resolved_place"] == "Malines, province d'Anvers, Belgique"

    def test_another_place_named_like_neither_is_still_refused(self, geo):
        # Negative control: an alias widens the echo to the request's own
        # names, not to anything — Machelen is neither Malines nor Mechelen.
        geo({("Mechelen", "BE"): [MACHELEN], ("Mechelen", None): [MACHELEN]})
        intent = GeoIntent(places=[Place(mention="Malines", kind="city", canonical="Mechelen",
                                         country="BE")])

        result = geocode_location(intent=intent, locale="fr", tool_context=_ctx("Malines"))

        assert result["ok"] is False
        assert "Machelen" not in str(result.get("clarification"))


class TestANeighbourhoodOfTheNamedCity:
    def test_clayton_is_accepted_inside_melbourne(self, geo):
        # Prod trace 27493242: « Westall, Clayton », Melbourne -> « Clayton,
        # Victoria, Australia » refused because it does not repeat Melbourne.
        geo({("Westall, Clayton, Melbourne", "AU"): _ranked(CLAYTON, MELBOURNE)})
        intent = GeoIntent(
            places=[Place(mention="Westall Clayton Melbourne area", kind="neighborhood",
                          canonical="Westall, Clayton", city="Melbourne", country="AU")],
            city=CityRef(mention="melbourne", canonical="Melbourne", country="AU"),
            relation="near",
        )

        result = geocode_location(
            intent=intent, tool_context=_ctx("A motel near Westall Clayton Melbourne area")
        )

        assert result["ok"] is True
        assert result["resolved_place"] == "Clayton, Victoria, Australia"
        assert result["distance_origin_type"] == "poi"

    def test_a_namesake_far_from_the_city_is_not_inside_it(self, geo):
        far_clayton = _c("Clayton", "Clayton, New South Wales, Australia", "AU", "New South Wales",
                         ftype="locality", lat=-33.0, lon=151.0)
        geo({("Westall, Clayton, Melbourne", "AU"): _ranked(far_clayton, MELBOURNE)})
        intent = GeoIntent(
            places=[Place(mention="Westall Clayton", kind="neighborhood",
                          canonical="Westall, Clayton", city="Melbourne", country="AU")],
        )

        result = geocode_location(intent=intent, tool_context=_ctx("near Westall Clayton"))

        assert result.get("resolved_place") != far_clayton.place_name


# --- A3: one retry without the earlier turns' place ----------------------------


class TestOneRetryWithoutTheCarriedPlace:
    def test_monaco_after_alpes_maritimes(self, geo):
        # Prod trace b6f8c8f4: « Entre Monaco et Toulon » after « le 06 »; the
        # carried zone made the query « Alpes-Maritimes, Monaco ».
        v6, _ = geo({
            ("Alpes-Maritimes, Monaco", "MC"): [MONACO],
            ("Alpes-Maritimes, Monaco", None): [MONACO],
            ("Monaco", "MC"): [MONACO],
        })
        intent = GeoIntent(places=[
            Place(mention="Monaco", kind="city", canonical="Monaco", country="MC"),
            Place(mention="Toulon", kind="city", canonical="Toulon", country="FR"),
        ], relation="in", carryover="new")

        result = geocode_location(
            intent=intent,
            tool_context=_ctx("Entre Monaco et Toulon", profile_in={"zone": "Alpes-Maritimes"}),
        )

        assert result["ok"] is True
        assert result["resolved_place"] == "Monaco"
        assert ("Monaco", "MC", None) in v6.calls

    def test_never_more_than_one_retry(self, geo):
        v6, _ = geo({})
        intent = GeoIntent(places=[Place(mention="Monaco", kind="city", canonical="Monaco",
                                         country="MC")])

        result = geocode_location(
            intent=intent, tool_context=_ctx("Monaco", profile_in={"zone": "Alpes-Maritimes"}),
        )

        assert result["ok"] is False
        queries = {q for q, _, _ in v6.calls}
        assert queries == {"Alpes-Maritimes, Monaco", "Monaco"}


# --- A4: the honest end is a question, never the outage line --------------------


class TestTheHonestEndIsAQuestion:
    def test_nothing_the_user_named_came_back(self, geo):
        geo({("Ojai", None): [OOST], ("Ojai", "US"): []})

        result = geocode_location(intent=_city("Ojai", "Ojai", "US"), tool_context=_ctx("Ojai"))

        assert result["error"] == "geocode_ambiguous"
        Clarification.model_validate(result["clarification"])
        assert result["clarification"] == {
            "schema_version": "1", "kind": "unresolved", "subject": "Ojai", "options": [],
        }
        assert "Oost" not in result["diagnostics"]["question"]

    def test_the_concierge_gets_a_question_not_an_empty_turn(self, geo):
        # What used to happen: a DataPart with `guards_fired` only, no text —
        # the concierge read an empty leaf turn and served "I can't reach the
        # hotel search right now".
        geo({("Ojai", None): [OOST], ("Ojai", "US"): []})
        result = geocode_location(
            intent=_city("Ojai", "Ojai", "US"), locale="en", tool_context=_ctx("Ojai")
        )

        data, text = _through_the_leaf(result)

        assert data["requires_clarification"] is True
        assert data["clarification"]["kind"] == "unresolved"
        assert "Ojai" in text
        assert "status" not in data  # not `search_unavailable`


# --- B: an administrative area is searched as one -------------------------------


def _area(mention, canonical, kind, country) -> Place:
    return Place(mention=mention, kind=kind, canonical=canonical, country=country)


class TestAnAreaIsSearchedAsOne:
    def test_le_06_is_searched_around_nice(self, geo):
        # Prod trace 5f8cb239: « Dans le 06 ou le 83 » -> the LLM read
        # Alpes-Maritimes and Var; the code checks the area exists in Mapbox.
        v6, box = geo({("Alpes-Maritimes", "FR", "area"): _ranked(ALPES_MARITIMES)})
        intent = GeoIntent(places=[
            _area("06", "Alpes-Maritimes", "admin_district", "FR"),
            _area("83", "Var", "admin_district", "FR"),
        ], relation="whole_city", carryover="new")

        result = geocode_location(intent=intent, locale="fr",
                                  tool_context=_ctx("Dans le 06 ou le 83"))

        assert result["ok"] is True
        assert (result["latitude"], result["longitude"]) == (43.701, 7.268)
        assert result["distance_origin_type"] == "city_centroid"
        assert result["profile_delta"]["last_city"] == "Alpes-Maritimes"
        assert "clarification" not in result
        assert v6.calls == [("Alpes-Maritimes", "FR", AREA_TYPES)]
        assert box.calls == []

    def test_the_herault_without_any_city(self, geo):
        geo({("Hérault", "FR", "area"): [HERAULT]})
        intent = GeoIntent(places=[_area("l'hérault", "Hérault", "admin_district", "FR")])

        result = geocode_location(intent=intent, locale="fr", tool_context=_ctx("dans l'hérault"))

        assert result["ok"] is True
        assert result["resolved_place"] == "Hérault, France"

    def test_puglia(self, geo):
        geo({("Puglia", "IT", "area"): [PUGLIA]})
        intent = GeoIntent(places=[_area("Puglia", "Puglia", "region", "IT")])

        result = geocode_location(intent=intent, locale="it", tool_context=_ctx("Puglia"))

        assert result["ok"] is True
        assert result["country_code"] == "IT"

    def test_the_earlier_city_is_never_searched_in_the_area(self, geo):
        # Prod trace a07181aa: « Cerca sul lago di como » after Sirmione was
        # looked up as « Lago di Como, Sirmione » -> a hamlet near Bergamo.
        v6, box = geo(
            {("Lago di Como, Sirmione", "IT"): [LAGO_DOSSENA]},
            {("Lago di Como", "IT"): [LAGO_COMO_POI]},
        )
        intent = GeoIntent(places=[_area("lago di como", "Lago di Como", "region", "IT")],
                           relation="near", carryover="new")

        result = geocode_location(
            intent=intent, locale="it",
            tool_context=_ctx("Cerca sul lago di como", profile_in={"city": "Sirmione"}),
        )

        assert result["ok"] is True
        assert result["resolved_place"] == "Lago como, 22017 Menaggio, Italia"
        assert all("Sirmione" not in q for q, _, _ in v6.calls)

    def test_peu_importe_la_ville_searches_the_area_again(self, geo):
        # The follow-up names no place: the area is the carried destination
        # (`last_city` + `city_is_area`), looked up again AS AN AREA — no city
        # question. This test used to serve the département on the city lookup,
        # which the real geocoder does not do (session 1eb2430a, class C).
        v6, _ = geo({
            ("Alpes-Maritimes", "FR"): _ranked(ALPES_VALENCE),
            ("Alpes-Maritimes", "FR", "area"): [ALPES_MARITIMES],
        })

        result = geocode_location(
            intent=GeoIntent(), locale="fr",
            tool_context=_ctx("Peu importe la ville",
                              profile_in={"city": "Alpes-Maritimes", "city_is_area": True,
                                          "country_anchor": "FR"}),
        )

        assert result["ok"] is True
        assert result["resolved_place"] == "Alpes-Maritimes, France"
        assert v6.calls == [("Alpes-Maritimes", "FR", AREA_TYPES)]

    def test_an_area_mapbox_does_not_know_is_an_honest_question(self, geo):
        geo({})
        intent = GeoIntent(places=[_area("la riviera", "Riviera", "region", "FR")])

        result = geocode_location(intent=intent, locale="fr", tool_context=_ctx("sur la riviera"))

        assert result["error"] == "geocode_ambiguous"
        assert result["clarification"]["kind"] == "unresolved"
        # Never the old zone-without-city question.
        assert result["clarification"]["kind"] != "city_needed"

    def test_a_landmark_without_a_city_still_asks_which_city(self, geo):
        # Negative control: the S5 rule is untouched — only an AREA kind takes
        # the new path.
        v6, _ = geo({})
        intent = GeoIntent(places=[Place(mention="gare de Lyon", kind="station",
                                         canonical="Gare de Lyon")])

        result = geocode_location(intent=intent, locale="fr",
                                  tool_context=_ctx("près de la gare de Lyon"))

        assert result["clarification"]["kind"] == "city_needed"
        assert v6.calls == []


# --- C. Session 1eb2430a: « Île-de-France », then the thread was lost ---------
#
# T1 « partout en Île de France » took the area branch. T2 « une chambre très
# classe » named no place: the area, carried as `last_city`, was looked up as a
# CITY and came back as a homonym question (a place called « Ile de France » in
# Les Ulis, the île de Ré). T3 « Dans toute Ile de France autour de paris »:
# the region became a landmark of Paris (« Parcs, Romainville », 5 km ring, 0
# hotel; 18 around Paris). T5 « Autour de saint ouen sur seine »: the carried
# zone « Île-de-France » made it a 2 km search (1 hotel; 19 around the city).
# The echo guard passes all of them: of « Île-de-France » only « france »
# (4 letters or more) is checked.

IDF = _c("Île-de-France", "Île-de-France, France", "FR", "Île-de-France", ftype="region",
         lat=48.922, lon=2.357)
IDF_LES_ULIS = _c("Ile de France", "Ile de France, Les Ulis, Essonne, France", "FR", "Essonne",
                  ftype="neighborhood", lat=48.68, lon=2.17)
ILE_DE_RE = _c("île de Ré", "île de Ré, Charente-Maritime, France", "FR", "Charente-Maritime",
               lat=46.2, lon=-1.4)
PARIS = _c("Paris", "Paris, Île-de-France, France", "FR", "Île-de-France", lat=48.857, lon=2.352)
PARCS_ROMAINVILLE = _c("Parcs", "Parcs, Romainville, Seine-Saint-Denis, France", "FR",
                       "Seine-Saint-Denis", ftype="neighborhood", lat=48.886, lon=2.439)
SAINT_OUEN = _c("Saint-Ouen-sur-Seine", "Saint-Ouen-sur-Seine, Seine-Saint-Denis, France", "FR",
                "Seine-Saint-Denis", lat=48.912, lon=2.334)
INVENTORY.update({48.922: 300, 48.68: 40, 46.2: 6, 48.857: 400, 48.886: 250, 48.912: 300})

#: The prod intent of T1, from the trace.
IDF_INTENT = GeoIntent(
    places=[Place(mention="Île de France", kind="region", canonical="Île-de-France", country="FR")],
    relation="whole_city", carryover="new",
)
#: What the concierge holds after T1, as the leaf receives it.
AFTER_T1 = {"city": "Île-de-France", "city_is_area": True, "country_anchor": "FR"}


class TestSession1eb2430a:
    def test_t1_the_area_is_marked_as_an_area(self, geo):
        geo({("Île-de-France", "FR", "area"): [IDF]})
        result = geocode_location(
            intent=IDF_INTENT, locale="fr",
            tool_context=_ctx("Je cherche partout en Île de France une chambre hyper belle"),
        )
        assert result["ok"] is True
        assert result["profile_delta"]["city_is_area"] is True
        data, _ = _through_the_leaf(result)
        assert data["profile_delta"]["city_is_area"] == {"op": "set", "value": True}

    def test_t2_a_turn_naming_no_place_searches_the_area_again(self, geo):
        # The city lookup of « Île-de-France » answers the homonyms prod asked
        # about; the area lookup answers the region. Only the latter may run.
        v6, _ = geo({
            ("Île-de-France", "FR"): _ranked(IDF_LES_ULIS, ILE_DE_RE, IDF),
            ("Île-de-France", "FR", "area"): [IDF],
        })
        result = geocode_location(
            intent=GeoIntent(), locale="fr",
            tool_context=_ctx("Je veux une chambre très classe", profile_in=AFTER_T1),
        )
        assert result["ok"] is True, result
        assert result["resolved_place"] == "Île-de-France, France"
        assert result["distance_origin_type"] == "city_centroid"
        assert all(types == AREA_TYPES for _, _, types in v6.calls)

    def test_t3_a_region_named_with_a_city_searches_the_city(self, geo):
        v6, _ = geo({
            ("Paris", "FR"): [PARIS],
            ("Île-de-France, Paris", "FR"): [PARCS_ROMAINVILLE],
        })
        intent = GeoIntent(
            places=[Place(mention="Ile de France", kind="region", canonical="Île-de-France", country="FR")],
            city=CityRef(mention="paris", canonical="Paris", country="FR"),
            country_named="FR", relation="whole_city", carryover="refine",
        )
        result = geocode_location(
            intent=intent, locale="fr",
            tool_context=_ctx("Dans toute Ile de France autour de paris", profile_in=AFTER_T1),
        )
        assert result["ok"] is True, result
        assert result["resolved_place"] == "Paris, Île-de-France, France"
        assert result["distance_origin_type"] == "city_centroid"
        assert "zone" not in result["profile_delta"]
        assert not any("Parcs" in str(c) or q.startswith("Île-de-France,") for q, *c in v6.calls)

    def test_t5_a_new_city_does_not_inherit_the_carried_zone(self, geo):
        v6, _ = geo({
            ("Saint-Ouen-sur-Seine", "FR"): [SAINT_OUEN],
            ("Île-de-France, Saint-Ouen-sur-Seine", "FR"): [SAINT_OUEN],
        })
        intent = GeoIntent(
            places=[Place(mention="saint ouen sur seine", kind="city", canonical="Saint-Ouen-sur-Seine",
                          country="FR")],
            city=CityRef(mention="saint ouen sur seine", canonical="Saint-Ouen-sur-Seine", country="FR"),
            relation="near", carryover="new",
        )
        result = geocode_location(
            intent=intent, locale="fr",
            tool_context=_ctx("Autour de saint ouen sur seine",
                              profile_in={"city": "Paris", "zone": "Île-de-France", "country_anchor": "FR"}),
        )
        assert result["ok"] is True, result
        assert result["distance_origin_type"] == "city_centroid"
        assert "zone" not in result["profile_delta"]
        assert not any("Île-de-France" in q for q, _, _ in v6.calls)

    def test_the_same_city_keeps_its_zone(self, geo):
        # Negative control of T5: naming the carried city again keeps the zone.
        v6, _ = geo({("Gare du Nord, Paris", "FR"): [PARCS_ROMAINVILLE], ("Paris", "FR"): [PARIS]})
        geocode_location(
            intent=GeoIntent(city=CityRef(mention="Paris", canonical="Paris", country="FR")), locale="fr",
            tool_context=_ctx("à Paris", profile_in={"city": "Paris", "zone": "Gare du Nord", "country_anchor": "FR"}),
        )
        assert any(q == "Gare du Nord, Paris" for q, _, _ in v6.calls)


# Prod session 7e296e4b (2026-10-27, release cb361c0): « new york city or long
# island » -> Search Box's « The Long Island Bar » in Brooklyn, a 2 km ring with a
# hot tub filter, 0 hotel. The exact intent below is already searched city-wide
# since d20af35 (a region named with its city); the same bar still came back
# when the model labelled the place another area kind, or named no city.
NYC = _c("New York", "New York, New York, United States", "US", "New York", lat=40.713, lon=-74.006)
LONG_ISLAND_BAR = _c(
    "The Long Island Bar", "The Long Island Bar, 110 Atlantic Ave, Brooklyn, New York 11201, United States",
    "US", "New York", ftype="poi", lat=40.690, lon=-73.996,
)
DETROIT_HOSPITAL = _c(
    "Metropolitan Detroit Area Hospital Services",
    "Metropolitan Detroit Area Hospital Services, 1150 Elijah McCoy Dr, Detroit, Michigan 48202, United States",
    "US", "Michigan", ftype="poi", lat=42.358, lon=-83.072,
)
CHATELET_POI = _c("Châtelet", "Châtelet, 75001 Paris, France", "FR", "Île-de-France", ftype="poi",
                  lat=48.858, lon=2.347)
INVENTORY.update({40.713: 150, 40.69: 40, 42.358: 12, 48.858: 90})

_NEW_YORK_CITY = CityRef(mention="new york city", canonical="New York City", country="US")


def _nyc_and_long_island(kind: str) -> GeoIntent:
    return GeoIntent(
        places=[
            Place(mention="new york city", kind="city", canonical="New York City", country="US"),
            _area("long island", "Long Island", kind, "US"),
        ],
        city=_NEW_YORK_CITY, relation="whole_city", carryover="new",
    )


class TestAnAreaIsNeverABusinessNamedAfterIt:
    @pytest.fixture
    def nyc(self, geo):
        return geo(
            {("New York City, New York", "US"): [NYC], ("New York City", "US"): [NYC]},
            {("Long Island", "US"): [LONG_ISLAND_BAR]},
        )

    def test_the_prod_intent_searches_the_whole_city(self, nyc):
        result = geocode_location(
            intent=_nyc_and_long_island("region"), locale="en",
            tool_context=_ctx("new york city or long island"),
        )

        assert result["ok"] is True, result
        assert result["distance_origin_type"] == "city_centroid"
        assert result["resolved_place"] == "New York, New York, United States"
        assert "zone" not in result["profile_delta"]

    @pytest.mark.parametrize("kind", ["admin_district", "neighborhood"])
    def test_another_area_kind_falls_back_to_the_whole_city(self, nyc, kind):
        result = geocode_location(
            intent=_nyc_and_long_island(kind), locale="en",
            tool_context=_ctx("new york city or long island"),
        )

        assert result["ok"] is True, result
        assert result["distance_origin_type"] == "city_centroid"
        assert result["resolved_place"] == "New York, New York, United States"
        assert "zone" not in result["profile_delta"]
        assert "geocode_echo_back" in result["guards_fired"]

    def test_an_area_with_no_city_is_never_the_business(self, geo):
        # Prod a407144 (2026-10-28): « metro Detroit » -> a hospital services
        # company. Not an area Mapbox's admin layer knows, no city to fall back on.
        geo({}, {("Metro Detroit", "US"): [DETROIT_HOSPITAL]})
        intent = GeoIntent(places=[_area("metro detroit", "Metro Detroit", "region", "US")],
                           relation="whole_city", carryover="new")

        result = geocode_location(intent=intent, locale="en",
                                  tool_context=_ctx("day room in metro detroit"))

        assert result["ok"] is False
        assert "latitude" not in result
        assert "geocode_echo_back" in result["guards_fired"]

    def test_the_area_under_its_own_name_is_kept(self, geo):
        geo({("Paris", "FR"): [PARIS]}, {("Châtelet", "FR"): [CHATELET_POI]})
        intent = GeoIntent(
            places=[Place(mention="paris", kind="city", canonical="Paris", country="FR"),
                    _area("chatelet", "Châtelet", "neighborhood", "FR")],
            city=CityRef(mention="paris", canonical="Paris", country="FR"),
            relation="in", carryover="new",
        )

        result = geocode_location(intent=intent, locale="fr",
                                  tool_context=_ctx("un hôtel à châtelet à paris"))

        assert result["ok"] is True, result
        assert result["resolved_place"] == "Châtelet, 75001 Paris, France"
        assert result["profile_delta"]["zone"] == "Châtelet"


@pytest.mark.parametrize(
    ("poi_name", "kind", "names", "business"),
    [
        # Prod 2026-10-15/28, every area place that came back as a Search-Box poi.
        ("The Long Island Bar", "region", ("Long Island", "New York City"), True),
        ("Metropolitan Detroit Area Hospital Services", "region", ("metro Detroit",), True),
        ("Centro Lampo Roma", "neighborhood", ("Centro", "Roma"), True),
        ("Bergen County Islamic Center", "admin_district", ("Bergen County",), True),
        ("China Sea Milton", "region", ("the sea",), True),
        ("Châtelet", "neighborhood", ("Châtelet", "Paris"), False),
        ("Basovizza", "neighborhood", ("Basovizza", "Trieste"), False),
        ("Manhattan", "neighborhood", ("Manhattan", "New York"), False),
        ("Lago como", "region", ("lago di como", "Lago di Como"), False),
        ("Métropole Européenne de Lille | Lille", "region",
         ("métropole lilloise", "Métropole européenne de Lille", "Lille"), False),
        # A landmark is a poi by nature: never judged on its name here.
        ("The Long Island Bar", "landmark", ("Long Island", "New York City"), False),
    ],
)
def test_a_business_only_borrows_the_area_name(poi_name, kind, names, business):
    poi = _c(poi_name, poi_name, "US", "", ftype="poi")

    assert geocode_tool._business_named_after_the_area(poi, zone_kind=kind, names=names) is business
