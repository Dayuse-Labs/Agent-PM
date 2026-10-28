"""Prod 2026-10-27/28 (traces Langfuse, release b446a65): anchors that put the
search in the wrong place.

a. « Di pomeriggio e in centro » (Rome, session c2f47e81): the centre of the
   city was looked up as a place, and « Centro Lampo Roma », a business 6 km
   out, became the origin of a 5 km ring (1 hotel, 18,6 km).
b. « Dans le 94 » (session 72c83c93): the département came back as « Marne,
   Neuilly-Plaisance, Seine-Saint-Denis » — the 93.
c. « Paris possiblement à côté de l'unesco » (session b4703f31): a homonym
   question Paris (Roanne) / Paris (Maine) without the capital, then « Paris la
   capitale de la France » → « Je n'ai pas réussi à situer « UNESCO
   Headquarters » » with `resolved_place` « Paris, France » in the same result.

Each `GeoIntent` is the one the leaf's model really sent (tool input in the
trace). The candidate lists are what Mapbox v6 and Search Box really returned,
probed live on 2026-10-28 (coordinates as returned), and the inventory counts
are the snapshot's (25 km). Offline: the APIs are fakes answering per query.
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

from b2c_common.geo_intent import GeoIntent
from hotel_search_agent import geocode_tool
from hotel_search_agent.fr_departments import FR_DEPARTMENTS, department
from hotel_search_agent.geocode_tool import geocode_location
from hotel_search_agent.mapbox_client import GeocodeCandidate
from hotel_search_agent.response_bridge import capture_after_tool, emit_search_datapart


def _c(name, place_name, cc, region, formatted, *, ftype="place", lat=0.0, lon=0.0, rank=0):
    return GeocodeCandidate(
        latitude=lat, longitude=lon, name=name, place_name=place_name,
        place_formatted=formatted, feature_type=ftype, country_code=cc, region=region,
        bbox=None, rank=rank,
    )


# --- Mapbox v6 / Search Box, probed live 2026-10-28 --------------------------
PARIS = _c("Paris", "Paris, France", "FR", "Paris", "France", lat=48.853495, lon=2.348392)
PARIS_ROANNE = _c("Paris", "Paris, Roanne, Loire, France", "FR", "Loire", "Roanne, Loire, France",
                  ftype="neighborhood", lat=46.0457, lon=4.0702, rank=1)
HEADQUARTERS_KY = _c("Headquarters", "Headquarters, Kentucky, États-Unis", "US", "Kentucky",
                     "Kentucky, États-Unis", ftype="locality", lat=38.3586, lon=-84.1144)
PARIS_MAINE = _c("Paris", "Paris, Maine, États-Unis", "US", "Maine", "Maine, États-Unis",
                 ftype="locality", lat=44.2598, lon=-70.5007, rank=2)
PARIS_OHIO = _c("Paris", "Paris, Ohio, États-Unis", "US", "Ohio", "Ohio, États-Unis",
                ftype="locality", lat=40.7977, lon=-81.165, rank=3)
PARIS_TEXAS = _c("Paris", "Paris, Texas, États-Unis", "US", "Texas", "Texas, États-Unis",
                 lat=33.6606, lon=-95.5563, rank=1)
UNESCO = _c("UNESCO", "7 Pl. de Fontenoy-Unesco, 75007 Paris, France", "FR", "", "",
            ftype="poi", lat=48.8497, lon=2.306)

VAL_DE_MARNE = _c("Val-de-Marne", "Val-de-Marne, France", "FR", "Val-de-Marne", "France",
                  ftype="region", lat=48.7771, lon=2.4531)
MARNE = _c("Marne", "Marne, France", "FR", "Marne", "France", ftype="region", lat=48.9566,
           lon=4.3629, rank=1)
MARNE_NEUILLY = _c("Marne", "Marne, Neuilly-Plaisance, Seine-Saint-Denis, France", "FR",
                   "Seine-Saint-Denis", "Neuilly-Plaisance, Seine-Saint-Denis, France",
                   ftype="neighborhood", lat=48.86245, lon=2.504412, rank=2)
CRETEIL = _c("Créteil", "Créteil, Val-de-Marne, France", "FR", "Val-de-Marne",
             "Val-de-Marne, France", lat=48.7794, lon=2.4546)

ROMA = _c("Roma", "Roma, città metropolitana di Roma Capitale, Italia", "IT", "Roma",
          "città metropolitana di Roma Capitale, Italia", lat=41.9, lon=12.4767)
ROMA_METRO = _c("città metropolitana di Roma Capitale", "città metropolitana di Roma Capitale, Italia",
                "IT", "Roma", "Italia", ftype="region", lat=41.8933, lon=12.4829, rank=1)
CENTRO_LAMPO = _c("Centro Lampo Roma", "Centro Lampo Roma, Via Oderisi da Gubbio, 00146 Roma, Italia",
                  "IT", "", "", ftype="poi", lat=41.8634, lon=12.4645)

#: Hotels within 25 km in the inventory snapshot, probed 2026-10-28.
INVENTORY = {48.853: 783, 46.046: 2, 44.26: 0, 38.359: 0, 40.798: 1, 33.661: 1,
             48.777: 751, 48.779: 768, 41.9: 130}

AREA_TYPES = "region,district"


class _V6:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def geocode_candidates(self, query, *, country=None, language=None, proximity=None,
                           types=None, **kwargs):
        key = (query, (country or "").upper() or None)
        self.calls.append((*key, types))
        if types == AREA_TYPES:
            return list(self.answers.get((*key, "area"), []))
        return list(self.answers.get(key, []))


class _SearchBox:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def forward_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, country, proximity))
        return list(self.answers.get(query, []))


class _Inventory:
    def count_near(self, lat, lon, *, radius_km=25.0):
        return INVENTORY.get(round(lat, 3), 0)


@pytest.fixture
def geo(monkeypatch):
    def patch(v6, box=None):
        fake_v6, fake_box = _V6(v6), _SearchBox(box or {})
        monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: fake_v6)
        monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: fake_box)
        monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _Inventory())
        return fake_v6, fake_box
    return patch


def _ctx(text, profile_in=None):
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": profile_in or {}})
    )
    parts = [genai_types.Part(text=text), convert_a2a_part_to_genai_part(datapart)]
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


def _run(intent: dict, text: str, profile_in=None, locale="fr"):
    return geocode_location(
        intent=GeoIntent.model_validate(intent), locale=locale, language_hint=locale,
        tool_context=_ctx(text, profile_in),
    )


def _datapart(result: dict, profile_in=None, args=None) -> dict:
    ctx = _ctx("", profile_in)
    capture_after_tool(SimpleNamespace(name="geocode_location"), args or {}, ctx, result)
    content = emit_search_datapart(ctx)
    assert content is not None
    for part in content.parts:
        if part.inline_data is not None:
            return convert_genai_part_to_a2a_part(part).root.data
    return {}


# --- c. Paris + a landmark ------------------------------------------------------

UNESCO_T1 = {  # tool input of the trace, turn « Paris possiblement à côté de l'unesco »
    "places": [{"mention": "UNESCO", "kind": "landmark", "canonical": "UNESCO Headquarters",
                "city": "Paris", "country": "FR", "city_inferred": True}],
    "city": {"mention": "Paris", "canonical": "Paris", "country": "FR"},
    "relation": "near", "carryover": "new",
}
UNESCO_T2 = {  # turn « Paris la capitale de la France », the landmark carried by the profile
    "places": [{"mention": "Paris", "kind": "city", "canonical": "Paris", "country": "FR"},
               {"mention": "l’unesco", "kind": "landmark", "canonical": "UNESCO Headquarters",
                "city": "Paris", "country": "FR", "city_inferred": True}],
    "city": {"mention": "Paris", "canonical": "Paris", "country": "FR"},
    "country_named": "FR", "relation": "near", "carryover": "keep",
}
V6_PARIS = {
    ("UNESCO Headquarters, Paris", "FR"): [PARIS, PARIS_ROANNE],
    ("UNESCO Headquarters, Paris", None): [HEADQUARTERS_KY, PARIS_ROANNE, PARIS_MAINE, PARIS_OHIO],
    ("Paris", "FR"): [PARIS, PARIS_ROANNE],
    ("Paris", None): [PARIS, PARIS_TEXAS],
}


class TestALandmarkInParis:
    def test_the_unesco_is_found_where_the_user_said(self, geo):
        v6, box = geo(V6_PARIS, {"UNESCO Headquarters": [UNESCO]})

        result = _run(UNESCO_T1, "Paris possiblement à côté de l’unesco")

        # The Search Box answer is named after the user's own word « UNESCO »,
        # not after the canonical « UNESCO Headquarters »: both are accepted.
        assert result["ok"] is True
        assert result["resolved_place"] == "7 Pl. de Fontenoy-Unesco, 75007 Paris, France"
        assert result["distance_origin_type"] == "poi"

    def test_the_capital_found_by_the_scoped_lookup_keeps_its_scope(self, geo):
        # The scoped list held « Paris, France »; no candidate echoed the
        # landmark too, and the worldwide lookup (Kentucky, Roanne, Maine,
        # Ohio) made the homonym question.
        v6, _ = geo(V6_PARIS, {"UNESCO Headquarters": [UNESCO]})

        _run(UNESCO_T1, "Paris possiblement à côté de l’unesco")

        assert ("UNESCO Headquarters, Paris", None, None) not in v6.calls
        assert "Maine" not in str(v6.calls)

    def test_a_landmark_nobody_can_place_searches_the_city_and_says_so(self, geo):
        geo(V6_PARIS, {})

        result = _run(UNESCO_T1, "Paris possiblement à côté de l’unesco")

        assert result["ok"] is True
        assert result["resolved_place"] == "Paris, France"
        assert result["distance_origin_type"] == "city_centroid"
        assert result["landmark_unresolved"] == "UNESCO Headquarters"
        data = _datapart(result, {"zone": "UNESCO Headquarters"})
        # The profile forgets the spot, or every later turn would look it up.
        assert data["profile_delta"]["zone"] == {"op": "clear"}

    def test_the_homonym_question_of_a_city_comes_from_the_city_alone(self, geo):
        # No country from the model: the « UNESCO Headquarters, Paris » list is
        # the polluted one; the city alone is the capital, by its hotels.
        intent = {**UNESCO_T1, "places": [{**UNESCO_T1["places"][0], "country": None}],
                  "city": {"mention": "Paris", "canonical": "Paris"}}
        geo(V6_PARIS, {})

        result = _run(intent, "Paris possiblement à côté de l’unesco", locale="en")

        assert result.get("error") != "geocode_ambiguous"
        assert result["resolved_place"] == "Paris, France"
        assert result["landmark_unresolved"] == "UNESCO Headquarters"

    def test_turn_2_the_carried_landmark_is_dropped_and_said(self, geo):
        geo(V6_PARIS, {})

        result = _run(UNESCO_T2, "Paris la capitale de la France", {"zone": "UNESCO Headquarters"})

        assert result["ok"] is True
        assert result["resolved_place"] == "Paris, France"
        assert result["landmark_unresolved"] == "UNESCO Headquarters"

    def test_a_city_with_no_landmark_is_searched_as_before(self, geo):
        # Negative control: nothing to drop, no notice.
        geo(V6_PARIS)
        intent = {"places": [{"mention": "Paris", "kind": "city", "canonical": "Paris", "country": "FR"}],
                  "city": {"mention": "Paris", "canonical": "Paris", "country": "FR"}}

        result = _run(intent, "Paris demain")

        assert result["resolved_place"] == "Paris, France"
        assert "landmark_unresolved" not in result


# --- b. « Dans le 94 » ----------------------------------------------------------

DANS_LE_94 = {  # tool input of the trace
    "places": [{"mention": "94", "kind": "admin_district", "canonical": "Val-de-Marne", "city": "Paris",
                "country": "FR", "city_inferred": True}],
    "city": {"mention": "94", "canonical": "Val-de-Marne", "country": "FR"},
    "relation": "in", "carryover": "refine",
}
CARRIED_IDF = {"city": "Île-de-France", "city_is_area": True}


class TestADepartementByItsNumber:
    def test_le_94_is_the_val_de_marne_not_the_93(self, geo):
        geo({
            ("Val-de-Marne", "FR", "area"): [VAL_DE_MARNE, MARNE],
            ("Val-de-Marne, Paris", "FR"): [VAL_DE_MARNE, MARNE_NEUILLY],
        })

        result = _run(DANS_LE_94, "Dans le 94", CARRIED_IDF)

        assert result["ok"] is True
        assert result["resolved_place"] == "Val-de-Marne, France"
        assert "Seine-Saint-Denis" not in result["resolved_place"]
        assert result["profile_delta"] == {"last_city": "Val-de-Marne", "city_is_area": True}

    def test_the_table_picks_the_area_not_its_longest_word(self, geo):
        # « Val-de-Marne » echoes « Marne » by its longest word; the INSEE
        # table says which département the number is.
        geo({("Val-de-Marne", "FR", "area"): [MARNE, VAL_DE_MARNE]})

        result = _run(DANS_LE_94, "Dans le 94", CARRIED_IDF)

        assert result["resolved_place"] == "Val-de-Marne, France"

    def test_the_model_misnaming_the_number_is_corrected_by_the_table(self, geo):
        wrong = {**DANS_LE_94, "places": [{**DANS_LE_94["places"][0], "canonical": "Seine-Saint-Denis"}],
                 "city": None}
        geo({("Val-de-Marne", "FR", "area"): [VAL_DE_MARNE]})

        result = _run(wrong, "Dans le 94", CARRIED_IDF)

        assert result["resolved_place"] == "Val-de-Marne, France"

    def test_an_area_mapbox_does_not_know_is_searched_around_its_prefecture(self, geo):
        geo({("Val-de-Marne", "FR", "area"): [], ("Créteil", "FR"): [CRETEIL]})

        result = _run(DANS_LE_94, "Dans le 94", CARRIED_IDF)

        assert result["ok"] is True
        assert (result["latitude"], result["longitude"]) == (CRETEIL.latitude, CRETEIL.longitude)

    def test_a_postcode_is_not_a_departement(self, geo):
        # Negative control: « 75009 » keeps the postcode path (Q08).
        assert department("75009") is None
        assert department("dans le 94") is None

    @pytest.mark.parametrize("code,name", [("94", "Val-de-Marne"), ("2a", "Corse-du-Sud"),
                                           ("6", "Alpes-Maritimes"), ("971", "Guadeloupe")])
    def test_the_table(self, code, name):
        assert department(code)[0] == name

    def test_every_departement_is_in_the_table(self):
        assert len(FR_DEPARTMENTS) == 101


# --- a. « in centro » ------------------------------------------------------------

def _centro(kind):
    return {
        "relation": "in", "carryover": "keep",
        "city": {"mention": "", "canonical": "Rome", "country": "IT"},
        "places": [{"mention": "centro", "kind": kind, "canonical": "centro di Roma", "city": "Rome",
                    "country": "IT", "city_inferred": True}],
    }


V6_ROME = {
    ("centro di Roma, Rome", "IT"): [ROMA, ROMA_METRO],
    ("Rome", "IT"): [ROMA, ROMA_METRO],
}
BOX_ROME = {"centro di Roma": [CENTRO_LAMPO]}


class TestTheCentreOfACity:
    def test_the_centre_is_measured_from_the_city(self, geo):
        _, box = geo(V6_ROME, BOX_ROME)

        result = _run(_centro("city_centre"), "Di pomeriggio e in centro", {"city": "Rome"}, "it")

        assert result["ok"] is True
        assert result["resolved_place"] == "Roma, città metropolitana di Roma Capitale, Italia"
        # The tight, distance-sorted ring of a named spot, around the city point.
        assert result["distance_origin_type"] == "poi"
        assert result["profile_delta"]["zone_kind"] == "city_centre"
        assert box.calls == []  # never a business named « centro »

    def test_a_follow_up_keeps_the_centre(self, geo):
        _, box = geo(V6_ROME, BOX_ROME)
        carried = {"city": "Rome", "country_anchor": "IT", "zone": "centro di Roma", "zone_kind": "city_centre"}

        result = _run({}, "e domani?", carried, "it")

        assert result["resolved_place"] == "Roma, città metropolitana di Roma Capitale, Italia"
        assert result["distance_origin_type"] == "poi"
        assert box.calls == []

    def test_the_zone_kind_travels_with_the_zone(self, geo):
        geo(V6_ROME, BOX_ROME)
        result = _run(_centro("city_centre"), "Di pomeriggio e in centro", {"city": "Rome"}, "it")

        data = _datapart(result)

        assert data["profile_delta"]["zone_kind"] == {"op": "set", "value": "city_centre"}

    def test_a_new_zone_clears_the_kind_of_the_old_one(self, geo):
        geo(V6_ROME, {"Colosseo": [_c("Colosseo", "Colosseo, Piazza del Colosseo, 00184 Roma, Italia",
                                      "IT", "", "", ftype="poi", lat=41.8902, lon=12.4922)]})
        intent = {"places": [{"mention": "Colosseo", "kind": "landmark", "canonical": "Colosseo",
                              "city": "Rome", "country": "IT", "city_inferred": True}]}
        carried = {"city": "Rome", "country_anchor": "IT", "zone": "centro di Roma", "zone_kind": "city_centre"}

        result = _run(intent, "vicino al Colosseo", carried, "it")
        data = _datapart(result, carried, {"intent": intent})

        assert data["profile_delta"]["zone"] == {"op": "set", "value": "Colosseo"}
        # The new zone's own kind (point 3 keeps it for the ring's floor),
        # never the centre of the city it replaces.
        assert data["profile_delta"]["zone_kind"] == {"op": "set", "value": "landmark"}

    def test_a_district_that_comes_back_as_a_business_is_not_the_district(self, geo):
        # The model's kind of the trace (« neighborhood »): Search Box answers
        # a business. #169's rule (`_business_named_after_the_area`: « Lampo »
        # is in neither the place asked nor the city) refuses it, and the city
        # is searched — this branch relies on it instead of a rule of its own.
        geo(V6_ROME, BOX_ROME)

        result = _run(_centro("neighborhood"), "Di pomeriggio e in centro", {"city": "Rome"}, "it")

        assert result["ok"] is True
        assert "Centro Lampo" not in result["resolved_place"]
        assert result["resolved_place"] == "Roma, città metropolitana di Roma Capitale, Italia"
        assert "geocode_echo_back" in result.get("guards_fired", [])
