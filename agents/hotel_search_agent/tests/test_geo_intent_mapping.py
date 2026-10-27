"""QA14707 (Q07): the leaf extracts the place into a `GeoIntent`.

`geocode_location` is the tool the model sees. It takes a `GeoIntent` instead
of the free `city` / `zone` / `raw_user_message` strings, checks the model's
claims against the leaf's real input text, maps the object onto the flat
arguments of `geocode_core` (the pipeline, unchanged), fills the blanks from
`profile_in`, then calls it. Offline: Mapbox, Search Box and the inventory are
fakes, or the real `MapboxClient` over an `httpx.MockTransport`.

Raphael's traces (`phases/QA14707/DIAGNOSTIC.md`) are the cases:
  A « paris Gare du nord »  -> zone "Gare du Nord", city "" -> asked which city;
  B « Boulevard de la République Versailles » -> city "" -> Versailles lost.
"""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import httpx
import pytest
from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.adk.tools.function_tool import FunctionTool
from google.genai import types as genai_types

from b2c_common.geo_intent import Ambiguity, CityRef, GeoIntent, Place
from hotel_search_agent import geocode_tool
from hotel_search_agent.geocode_tool import geocode_core, geocode_location
from hotel_search_agent.mapbox_client import GeocodeCandidate, MapboxClient


def _c(name, cc, region, *, ftype="place", rank=0, lat=0.0, lon=0.0, place_name=None, place=""):
    return GeocodeCandidate(
        latitude=lat,
        longitude=lon,
        name=name,
        place_name=place_name or f"{name}, {region}, {cc}",
        place_formatted=f"{region}, {cc}",
        feature_type=ftype,
        country_code=cc,
        region=region,
        bbox=None,
        rank=rank,
        place=place,
    )


class _V6:
    """Mapbox v6, answering per query; records `(query, country)` per call."""

    def __init__(self, by_query=None):
        self.by_query = by_query or {}
        self.calls: list[tuple] = []

    def geocode_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, country))
        return list(self.by_query.get(query, []))


class _SearchBox:
    def __init__(self, *candidates):
        self.candidates = list(candidates)
        self.calls: list[tuple] = []

    def forward_candidates(self, query, *, country=None, language=None, proximity=None, **kwargs):
        self.calls.append((query, country, proximity))
        return list(self.candidates)


class _Inventory:
    def __init__(self, by_lat):
        self.by_lat = by_lat

    def count_near(self, lat, lon, *, radius_km=25.0):
        return self.by_lat.get(round(lat, 4), 0)


def _patch(monkeypatch, v6=None, box=None, inventory=None):
    v6 = v6 or _V6()
    box = box or _SearchBox()
    inv = _Inventory(inventory or {})
    monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: v6)
    monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)
    monkeypatch.setattr(geocode_tool, "get_inventory", lambda: inv)
    return v6, box


def _ctx(*texts, profile_in=None, query_params=None):
    """The leaf's `tool_context`: the inbound text part(s), then the A2A
    DataPart, as the real a2a→genai converter hands them to the leaf."""
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(
            data={"query_params": query_params or {}, "profile_in": profile_in or {}}
        )
    )
    parts = [genai_types.Part(text=text) for text in texts]
    parts.append(convert_a2a_part_to_genai_part(datapart))
    return SimpleNamespace(state={}, user_content=genai_types.Content(role="user", parts=parts))


@pytest.fixture
def metric(monkeypatch):
    """The `geo_intent` metric lines of the turn (the shared stdout logger)."""
    lines: list[str] = []
    monkeypatch.setattr(
        geocode_tool._metrics_logger, "info", lambda fmt, *a: lines.append(fmt % a)
    )
    return lambda: [line for line in lines if line.startswith("dayuse_metric=geo_intent ")]


@pytest.fixture
def statuses(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(
        geocode_tool, "mark_level", lambda level, status_message="": seen.append(status_message)
    )
    return seen


@pytest.fixture
def core(monkeypatch):
    """Spy: the flat arguments `geocode_location` hands the pipeline."""
    seen: list[dict] = []

    def spy(**kwargs):
        seen.append(kwargs)
        return {"ok": False, "error": "spy"}

    monkeypatch.setattr(geocode_tool, "geocode_core", spy)
    return seen


def _fields(line: str) -> dict[str, str]:
    return dict(token.split("=", 1) for token in line.split()[1:])


PARIS = _c("Paris", "FR", "Île-de-France", lat=48.8566, lon=2.3522)
GARE_DU_NORD = _c(
    "Gare du Nord", "FR", "Paris", ftype="poi", lat=48.8809, lon=2.3553,
    place_name="Gare du Nord, 75010 Paris, France",
)
#: A v6 answer to « Gare du Nord, Paris » that echoes neither: tier 1 falls
#: through, the city is geocoded on its own and aims the Search-Box lookup
#: (the anchored landmark path, `TestACityNameWithoutACoordinate`).
V6_MISS = _c("Nordhausen", "DE", "Thuringia", lat=51.5, lon=10.8)
PARIS_INVENTORY = {48.8566: 780, 48.8809: 300}


def _station(mention="Gare du Nord", **kwargs) -> Place:
    return Place(mention=mention, kind="station", canonical="Gare du Nord", **kwargs)


# --- Raphael's traces A and B -------------------------------------------------


class TestTheNamedCityIsKept:
    def test_a_gare_du_nord_in_paris_is_geocoded_in_paris_without_a_question(
        self, monkeypatch, statuses
    ):
        # Trace A: the model used to drop « paris » (city="") and the tool
        # asked which city. In the intent, the named city has its own field.
        v6, box = _patch(
            monkeypatch,
            _V6({"Gare du Nord, Paris": [V6_MISS], "Paris": [PARIS]}),
            _SearchBox(GARE_DU_NORD),
            PARIS_INVENTORY,
        )
        intent = GeoIntent(
            places=[_station(mention="Gare du nord")],
            city=CityRef(mention="paris", canonical="Paris"),
        )

        result = geocode_location(
            intent=intent, tool_context=_ctx("I need a room in paris Gare du nord tomorrow")
        )

        assert "geocode_city_needed" not in statuses
        assert "clarification" not in result
        assert result["ok"] is True
        assert result["resolved_place"] == "Gare du Nord, 75010 Paris, France"
        assert result["distance_origin_type"] == "poi"
        assert v6.calls == [("Gare du Nord, Paris", None), ("Paris", None)]
        # The station lookup is aimed at the verified Paris, query left bare.
        assert box.calls == [("Gare du Nord", None, "2.3522,48.8566")]

    def test_a_street_followed_by_versailles_keeps_versailles(self, monkeypatch, statuses):
        # Trace B: « Versailles » was buried in `zone` and the city lost.
        # `place` is the street's `context.place`, as Mapbox records it (H6
        # `street_bd_republique_versailles.json`): since Q20 the address lookup
        # takes the street on that equality, in the one call asserted below.
        street = _c(
            "Boulevard de la République", "FR", "Versailles", ftype="street",
            lat=48.8077, lon=2.1301,
            place_name="Boulevard de la République, 78000 Versailles, France",
            place="Versailles",
        )
        v6, _box = _patch(
            monkeypatch,
            _V6({"Boulevard de la République, Versailles": [street]}),
            inventory={48.8077: 12},
        )
        intent = GeoIntent(
            places=[Place(mention="Boulevard de la République", kind="street",
                          canonical="Boulevard de la République")],
            city=CityRef(mention="Versailles", canonical="Versailles"),
        )

        result = geocode_location(
            intent=intent,
            tool_context=_ctx("un hôtel Boulevard de la République Versailles demain"),
        )

        assert "geocode_city_needed" not in statuses
        assert result["ok"] is True
        assert v6.calls == [("Boulevard de la République, Versailles", None)]
        assert result["profile_delta"]["last_city"] == "Versailles"
        assert result["profile_delta"]["zone"] == "Boulevard de la République"


class TestTheCityQuestionStays:
    def test_gare_du_nord_with_no_city_still_asks_which_city(self, monkeypatch, statuses):
        # The case to keep: Paris and Brussels both have one.
        _v6, box = _patch(monkeypatch)

        result = geocode_location(
            intent=GeoIntent(places=[_station()]),
            locale="fr-FR",
            tool_context=_ctx("un hôtel près de Gare du Nord demain"),
        )

        assert result["error"] == "geocode_ambiguous"
        assert "geocode_city_needed" in statuses
        assert result["clarification"]["kind"] == "city_needed"
        assert result["clarification"]["subject"] == "Gare du Nord"
        assert result["clarification"]["options"] == []
        assert box.calls == []

    def test_gare_de_lyon_flagged_city_needed_asks_which_city(self, monkeypatch, statuses):
        # DQ6, the S5 rule as a field rule: the model flags, the code asks.
        v6, box = _patch(monkeypatch)
        intent = GeoIntent(
            places=[Place(mention="gare de Lyon", kind="station", canonical="Gare de Lyon")],
            ambiguity=Ambiguity(reason="city_needed"),
        )

        result = geocode_location(
            intent=intent, locale="fr-FR",
            tool_context=_ctx("hôtel près de la gare de Lyon demain"),
        )

        assert result["error"] == "geocode_ambiguous"
        assert "geocode_city_needed" in statuses
        assert result["clarification"]["kind"] == "city_needed"
        assert result["clarification"]["subject"] == "Gare de Lyon"
        assert v6.calls == [] and box.calls == []

    def test_the_flag_wins_over_the_false_lead_the_name_carries(self, monkeypatch, statuses):
        # The S5 trap itself: « Lyon » IS in the message, inside the station's
        # name. A model that flags city_needed and still fills Lyon is not
        # trusted on the city: no Lyon lookup, the question goes out.
        v6, _box = _patch(monkeypatch)
        intent = GeoIntent(
            places=[Place(mention="gare de Lyon", kind="station", canonical="Gare de Lyon",
                          city="Lyon")],
            city=CityRef(mention="Lyon", canonical="Lyon"),
            ambiguity=Ambiguity(reason="city_needed"),
        )

        result = geocode_location(
            intent=intent, tool_context=_ctx("hôtel près de la gare de Lyon demain")
        )

        assert result["error"] == "geocode_ambiguous"
        assert result["clarification"]["kind"] == "city_needed"
        assert v6.calls == []

    def test_the_flag_does_not_drop_the_city_the_profile_carries(self, core):
        # Carry-over is unchanged (S-L5 is out of scope): a Paris conversation
        # asking « et près de la gare de Lyon ? » keeps Paris, as before.
        intent = GeoIntent(
            places=[Place(mention="gare de Lyon", kind="station", canonical="Gare de Lyon")],
            ambiguity=Ambiguity(reason="city_needed"),
        )

        geocode_location(
            intent=intent,
            tool_context=_ctx("et près de la gare de Lyon ?", profile_in={"city": "Paris"}),
        )

        assert core[0]["city"] == "Paris"
        assert core[0]["zone"] == "Gare de Lyon"


# --- the code checks the model's claims ----------------------------------------


class TestMentionsAreCheckedAgainstTheMessage:
    def test_a_city_the_user_never_wrote_is_discarded_and_counted(
        self, monkeypatch, metric, statuses
    ):
        _patch(monkeypatch)
        intent = GeoIntent(
            places=[_station()],
            city=CityRef(mention="Paris", canonical="Paris"),  # not in the message
        )

        result = geocode_location(
            intent=intent, tool_context=_ctx("un hôtel près de Gare du Nord demain")
        )

        assert result["error"] == "geocode_ambiguous"
        assert "geocode_city_needed" in statuses
        [line] = metric()
        assert _fields(line)["mentions_discarded"] == "1"
        # GDPR: counts and closed enumerations, never a word of the message.
        for word in ("paris", "gare", "nord", "hôtel", "demain"):
            assert word not in line.lower()

    def test_a_place_the_user_never_wrote_is_discarded(self, core, metric):
        intent = GeoIntent(
            places=[Place(mention="Tour Eiffel", kind="landmark", canonical="Tour Eiffel")],
            city=CityRef(mention="Paris", canonical="Paris"),
        )

        geocode_location(intent=intent, tool_context=_ctx("un hôtel à Paris demain"))

        assert core[0]["zone"] is None
        assert core[0]["city"] == "Paris"
        assert _fields(metric()[0])["mentions_discarded"] == "1"

    def test_case_accents_and_punctuation_do_not_count(self, core, metric):
        intent = GeoIntent(
            places=[Place(mention="Champs-Élysées", kind="street", canonical="Champs-Élysées",
                          city="Paris")],
        )

        geocode_location(intent=intent, tool_context=_ctx("un hotel vers les champs elysees"))

        assert core[0]["zone"] == "Champs-Élysées"
        assert _fields(metric()[0])["mentions_discarded"] == "0"

    def test_the_earlier_request_prefix_anchors_the_place(self, monkeypatch, metric):
        # The answer turn: the concierge sends EARLIER REQUEST / YOU ASKED /
        # REPLY before the user's « Pari » (`pending_clarification_context`).
        # « Gare du Nord » is not in the reply, but it is in the leaf's input.
        prefix = (
            "EARLIER REQUEST (the user's own words, not searched yet): "
            "un hôtel près de Gare du Nord demain à 14h\n"
            'YOU ASKED: {"kind": "city_needed", "subject": "Gare du Nord", "options": []}\n'
            "REPLY:"
        )
        v6, _box = _patch(
            monkeypatch,
            _V6({"Paris": [PARIS], "Gare du Nord, Paris": [V6_MISS]}),
            _SearchBox(GARE_DU_NORD),
            PARIS_INVENTORY,
        )
        intent = GeoIntent(places=[_station()], city=CityRef(mention="Pari", canonical="Paris"))

        result = geocode_location(intent=intent, tool_context=_ctx(prefix, "Pari"))

        fields = _fields(metric()[0])
        assert fields["mentions_discarded"] == "0"
        assert fields["canonicals_rejected"] == "0"
        assert result["ok"] is True
        assert result["resolved_place"] == "Gare du Nord, 75010 Paris, France"
        # « Pari » -> « Paris » was checked as a real city first.
        assert v6.calls[0] == ("Paris", None)

    def test_the_message_is_read_from_the_invocation_never_the_question(self, core):
        prefix = "EARLIER REQUEST (the user's own words, not searched yet): hotel in Manhattan\n" \
                 'YOU ASKED: {"options": [{"region": "New York"}, {"region": "Kansas"}]}\nREPLY:'

        geocode_location(intent=GeoIntent(), tool_context=_ctx(prefix, "Kansas please"))

        # The user's own words, the last part: the YOU ASKED options name
        # every place of the question at once.
        assert core[0]["raw_user_message"] == "Kansas please"

    def test_without_an_invocation_nothing_is_anchored(self, core, metric):
        geocode_location(intent=GeoIntent(city=CityRef(mention="Paris", canonical="Paris")))

        assert core[0]["city"] == ""
        assert core[0]["raw_user_message"] == ""
        assert _fields(metric()[0])["mentions_discarded"] == "1"


class TestTheCanonicalCityIsChecked:
    def test_a_corrected_name_that_geocodes_to_a_city_with_inventory_is_kept(
        self, monkeypatch, core, metric
    ):
        asked: list[str] = []
        monkeypatch.setattr(
            geocode_tool, "_city_coordinate",
            lambda city, **kw: asked.append(city) or (48.8566, 2.3522),
        )

        geocode_location(
            intent=GeoIntent(city=CityRef(mention="Pari", canonical="Paris")),
            tool_context=_ctx("un hôtel à Pari"),
        )

        assert asked == ["Paris"]
        assert core[0]["city"] == "Paris"
        assert _fields(metric()[0])["canonicals_rejected"] == "0"

    def test_an_unverified_correction_falls_back_to_the_users_words(
        self, monkeypatch, core, metric
    ):
        monkeypatch.setattr(geocode_tool, "_city_coordinate", lambda city, **kw: None)

        geocode_location(
            intent=GeoIntent(city=CityRef(mention="Pari", canonical="Parisopolis")),
            tool_context=_ctx("un hôtel à Pari"),
        )

        assert core[0]["city"] == "Pari"
        assert _fields(metric()[0])["canonicals_rejected"] == "1"

    def test_the_same_name_costs_no_extra_lookup(self, monkeypatch, core):
        asked: list[str] = []
        monkeypatch.setattr(
            geocode_tool, "_city_coordinate", lambda city, **kw: asked.append(city)
        )

        geocode_location(
            intent=GeoIntent(places=[Place(mention="paris", kind="city", canonical="Paris")]),
            tool_context=_ctx("un hôtel à paris"),
        )

        assert asked == []
        assert core[0]["city"] == "Paris"


# --- countries: `_iso2` before any filter or hint ------------------------------


def _lyon_feature() -> dict:
    return {
        "geometry": {"coordinates": [4.8357, 45.764]},
        "properties": {
            "name": "Lyon",
            "full_address": "Lyon, Auvergne-Rhône-Alpes, France",
            "feature_type": "place",
            "context": {
                "country": {"country_code": "fr"},
                "region": {"name": "Auvergne-Rhône-Alpes"},
            },
        },
    }


class TestCountriesAreNormalized:
    @pytest.mark.parametrize(
        ("named", "sent"),
        [("fr", "fr"), ("FR", "fr"), ("France", None), ("USA", None), ("FRA", None)],
    )
    def test_country_named_reaches_mapbox_only_as_an_iso2_code(
        self, monkeypatch, metric, named, sent
    ):
        requests: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(dict(request.url.params))
            return httpx.Response(200, json={"features": [_lyon_feature()]})

        client = MapboxClient("test-token", client=httpx.Client(transport=httpx.MockTransport(handler)))
        monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: client)
        monkeypatch.setattr(geocode_tool, "get_inventory", lambda: _Inventory({45.764: 100}))
        intent = GeoIntent(
            places=[Place(mention="Lyon", kind="city", canonical="Lyon")], country_named=named
        )

        result = geocode_location(intent=intent, tool_context=_ctx("un hôtel à Lyon en France"))

        assert requests, "Mapbox was never called"
        assert [r.get("country") for r in requests] == [sent] * len(requests)
        # The rest of the intent is still geocoded.
        assert result["ok"] is True
        assert result["resolved_place"] == "Lyon, Auvergne-Rhône-Alpes, France"
        assert _fields(metric()[0])["countries_discarded"] == ("0" if sent else "1")

    @pytest.mark.parametrize(
        ("place_country", "city_country", "guess"),
        [
            ("fr", None, "FR"),
            ("France", None, None),
            (None, "es", "ES"),
            (None, "Spain", None),
            ("FRA", "it", "IT"),
        ],
    )
    def test_the_guess_goes_through_the_same_normalization(
        self, core, place_country, city_country, guess
    ):
        intent = GeoIntent(
            places=[Place(mention="la plaza mayor", kind="landmark", canonical="Plaza Mayor",
                          country=place_country)],
            city=CityRef(mention="Madrid", canonical="Madrid", country=city_country),
        )

        geocode_location(intent=intent, tool_context=_ctx("cerca de la plaza mayor en Madrid"))

        assert core[0]["country_guess"] == guess
        # A guess is a hint, never the hard filter.
        assert core[0]["country_code"] is None

    def test_a_named_country_wins_over_the_carried_anchor(self, core):
        intent = GeoIntent(
            places=[Place(mention="Lyon", kind="city", canonical="Lyon")], country_named="FR"
        )

        geocode_location(
            intent=intent,
            tool_context=_ctx("Lyon en France", profile_in={"country_anchor": "US"}),
        )

        assert core[0]["country_code"] == "FR"

    def test_a_malformed_named_country_leaves_the_carried_anchor(self, core):
        intent = GeoIntent(
            places=[Place(mention="Lyon", kind="city", canonical="Lyon")], country_named="France"
        )

        geocode_location(
            intent=intent,
            tool_context=_ctx("Lyon en France", profile_in={"country_anchor": "FR"}),
        )

        assert core[0]["country_code"] == "FR"


# --- an intent that fails validation -------------------------------------------


_INVALID = [
    {"places": [{"mention": "mars", "kind": "planet"}]},
    {"places": [{"mention": "a"}, {"mention": "b"}, {"mention": "c"}]},
    {"city": {"mention": "Paris"}, "latitude": 48.85},
    "Paris",
]


class TestAnInvalidIntentDegrades:
    @pytest.mark.parametrize("raw", _INVALID)
    def test_a_raw_dict_is_validated_never_used_and_counted(self, core, metric, raw):
        result = geocode_location(
            intent=raw,  # what ADK passes on a failed conversion
            tool_context=_ctx("un hôtel à mars a b c", profile_in={"city": "Paris"}),
        )

        assert result == {"ok": False, "error": "spy"}
        # As with an empty intent: the carry-over still applies, nothing raw.
        assert core[0]["city"] == "Paris"
        assert core[0]["zone"] is None
        fields = _fields(metric()[0])
        assert fields["valid"] == "0"
        assert fields["places"] == "0"

    def test_adk_passes_the_raw_dict_and_the_tool_copes(self, core, metric):
        # ADK 2.4 logs the failed conversion and hands the original value over.
        tool = FunctionTool(geocode_location)
        ctx = _ctx("un hôtel sur mars", profile_in={"city": "Paris"})

        result = asyncio.run(
            tool.run_async(args={"intent": _INVALID[0]}, tool_context=ctx)
        )

        assert result == {"ok": False, "error": "spy"}
        assert core[0]["city"] == "Paris"
        assert _fields(metric()[0])["valid"] == "0"


# --- Q17: one malformed field no longer voids the whole intent ----------------
#
# H3 (2026-10-15): 31 of 220 calls failed validation and ran on an empty
# intent — 29 with the intent-level `city` as a bare string (the model mixes
# it up with `Place.city`), 2 with a place of kind "date". The intents below
# are copied from the recorded traces, as ADK hands them over: a raw dict.


def _run_tool(intent: object, *texts: str, profile_in=None) -> dict:
    """The real `geocode_location` FunctionTool, as ADK runs it."""
    return asyncio.run(
        FunctionTool(geocode_location).run_async(
            args={"intent": intent}, tool_context=_ctx(*texts, profile_in=profile_in)
        )
    )


#: plan-r2 trace 1dc8ced4548bd034a88c8f591e076436 (qa14707-versailles-address-fr).
VERSAILLES_TEXT = "Trouve moi une chambre à Boulevard de la République Versailles pour 13h demain"
VERSAILLES_INTENT = {
    "places": [
        {
            "mention": "Boulevard de la République",
            "kind": "street",
            "canonical": "Boulevard de la République",
            "city": "Versailles",
        }
    ],
    "city": "Versailles",
}
#: plan-r1 trace 79eea59799c55c6da69d39dfcc055b77 (qa14707-gare-du-nord-en).
GARE_DU_NORD_EN_TEXT = "I want a room in paris Gare du nord for 10 am tomorrow"
GARE_DU_NORD_EN_INTENT = {
    "places": [{"mention": "Gare du nord", "kind": "station", "canonical": "Gare du Nord"}],
    "city": "Paris",
}
#: plan-r1 trace 492e82e61f24d23ea8d69694b4ee8bf6 (ds-clarify-keeps-date-monaco).
MONACO_DATE_INTENT = {
    "places": [
        {"mention": "samedi", "kind": "date", "canonical": "samedi"},
        {"mention": "10 octobre", "kind": "date", "canonical": "10 octobre"},
    ]
}


class TestAMalformedFieldIsRepaired:
    def test_the_versailles_trace_keeps_its_street_and_its_city(self, core, metric):
        result = _run_tool(VERSAILLES_INTENT, VERSAILLES_TEXT)

        assert result == {"ok": False, "error": "spy"}
        assert core[0]["zone"] == "Boulevard de la République"
        assert core[0]["zone_kind"] == "street"
        assert core[0]["city"] == "Versailles"
        fields = _fields(metric()[0])
        # `valid` still says what the model sent: it did not validate.
        assert fields["valid"] == "0"
        assert fields["repaired"] == "1"
        assert fields["places"] == "1"

    def test_the_gare_du_nord_trace_keeps_paris(self, core):
        _run_tool(GARE_DU_NORD_EN_INTENT, GARE_DU_NORD_EN_TEXT)

        assert core[0]["zone"] == "Gare du Nord"
        assert core[0]["city"] == "Paris"

    def test_the_gare_du_nord_trace_asks_no_city_question(self, monkeypatch, statuses):
        v6, box = _patch(
            monkeypatch,
            _V6({"Gare du Nord, Paris": [V6_MISS], "Paris": [PARIS]}),
            _SearchBox(GARE_DU_NORD),
            PARIS_INVENTORY,
        )

        result = _run_tool(GARE_DU_NORD_EN_INTENT, GARE_DU_NORD_EN_TEXT)

        assert "geocode_city_needed" not in statuses
        assert "clarification" not in result
        assert result["ok"] is True
        assert result["resolved_place"] == "Gare du Nord, 75010 Paris, France"
        assert v6.calls == [("Gare du Nord, Paris", None), ("Paris", None)]

    def test_a_repaired_city_the_user_never_wrote_is_still_dropped(
        self, monkeypatch, statuses, metric
    ):
        # Guard kept: the repaired city has no mention, so its canonical must be
        # in the text (`_Claims.anchored`). « Paris » is not: the city question
        # goes out, exactly as with a well-formed CityRef, and no lookup runs.
        v6, box = _patch(monkeypatch)
        intent = {"places": [{"mention": "Gare du Nord", "kind": "station",
                              "canonical": "Gare du Nord"}], "city": "Paris"}

        result = _run_tool(intent, "un hôtel près de la Gare du Nord demain")

        assert result["error"] == "geocode_ambiguous"
        assert "geocode_city_needed" in statuses
        assert result["clarification"]["kind"] == "city_needed"
        assert v6.calls == [] and box.calls == []
        assert _fields(metric()[0])["repaired"] == "1"

    @pytest.mark.parametrize("kind", ["date", "postal_code"])
    def test_a_place_of_an_unknown_kind_is_dropped_alone(self, core, metric, kind):
        intent = {
            "places": [
                {"mention": "demain", "kind": kind, "canonical": "demain"},
                {"mention": "Gare du Nord", "kind": "station", "canonical": "Gare du Nord",
                 "city": "Paris"},
            ]
        }

        _run_tool(intent, "un hôtel près de la Gare du Nord demain")

        assert core[0]["zone"] == "Gare du Nord"
        assert core[0]["zone_kind"] == "station"
        assert core[0]["city"] == "Paris"
        fields = _fields(metric()[0])
        assert fields["valid"] == "0"
        assert fields["repaired"] == "1"
        assert fields["places"] == "1"

    def test_the_monaco_trace_maps_to_no_place(self, core, metric):
        # Two dates in `places`: both dropped, nothing left to map — the same
        # as an empty intent, which is what the turn had before Q17.
        _run_tool(MONACO_DATE_INTENT, "je cherche un hôtel samedi 10 octobre")

        assert core[0]["zone"] is None
        assert core[0]["city"] == ""
        fields = _fields(metric()[0])
        assert fields["valid"] == "0"
        assert fields["repaired"] == "2"
        assert fields["places"] == "0"

    def test_both_repairs_count_and_the_line_holds_no_word(self, core, metric):
        intent = {**VERSAILLES_INTENT, "places": [
            *VERSAILLES_INTENT["places"],
            {"mention": "demain", "kind": "date", "canonical": "demain"},
        ]}

        _run_tool(intent, VERSAILLES_TEXT)

        assert core[0]["city"] == "Versailles"
        [line] = metric()
        fields = _fields(line)
        assert fields["valid"] == "0"
        assert fields["repaired"] == "2"
        # GDPR: counts and closed enumerations, never a word of the message.
        for word in ("versailles", "boulevard", "république", "chambre", "demain", "13h"):
            assert word not in line.lower()

    def test_the_recorded_intent_is_not_modified(self, core):
        # The tool works on a copy: ADK's dict (and these constants) stay as sent.
        before = repr(VERSAILLES_INTENT)

        _run_tool(VERSAILLES_INTENT, VERSAILLES_TEXT)

        assert repr(VERSAILLES_INTENT) == before

    def test_a_valid_intent_counts_no_repair(self, core, metric):
        _run_tool(
            {"places": [{"mention": "Gare du Nord", "kind": "station"}],
             "city": {"mention": "Paris", "canonical": "Paris"}},
            "Gare du Nord Paris",
        )

        fields = _fields(metric()[0])
        assert fields["valid"] == "1"
        assert fields["repaired"] == "0"

    @pytest.mark.parametrize(
        "raw",
        [
            # The other recorded failure: a repaired city, but an extra key.
            {**GARE_DU_NORD_EN_INTENT, "country": "FR"},
            # A repaired kind, but still three places.
            {"places": [{"mention": "a"}, {"mention": "b"}, {"mention": "c"},
                        {"mention": "demain", "kind": "date"}]},
            # A kind that is not a string (unhashable): never removed, never
            # raises, fails validation as before — even next to a repairable city.
            {"places": [{"mention": "Gare du nord", "kind": ["station"]}]},
            {"places": [{"mention": "Gare du nord", "kind": {"type": "station"}}],
             "city": "Paris"},
        ],
    )
    def test_anything_else_stays_all_or_nothing(self, core, metric, raw):
        _run_tool(raw, "I want a room in paris Gare du nord demain a b c",
                  profile_in={"city": "Lyon"})

        assert core[0]["city"] == "Lyon"
        assert core[0]["zone"] is None
        fields = _fields(metric()[0])
        assert fields["valid"] == "0"
        assert fields["repaired"] == "0"
        assert fields["places"] == "0"


# --- the real tool's declaration -----------------------------------------------


class TestTheRealTool:
    def test_a_dict_intent_arrives_as_a_geo_intent(self, monkeypatch, core):
        received: list[object] = []
        real = geocode_tool._valid_intent

        def spy(intent):
            received.append(intent)
            return real(intent)

        monkeypatch.setattr(geocode_tool, "_valid_intent", spy)
        tool = FunctionTool(geocode_location)
        args = {"intent": {"places": [{"mention": "Gare du Nord", "kind": "station"}],
                           "city": {"mention": "Paris", "canonical": "Paris"}}}

        asyncio.run(tool.run_async(args=args, tool_context=_ctx("Gare du Nord Paris")))

        assert isinstance(received[0], GeoIntent)
        assert core[0]["city"] == "Paris"
        assert core[0]["zone"] == "Gare du Nord"

    def test_the_parameter_is_declared_as_the_class_with_a_default(self):
        intent = inspect.signature(geocode_location).parameters["intent"]
        # Under `from __future__ import annotations`: the class itself, the one
        # form ADK 2.4 converts (`GeoIntent | None` never does).
        assert intent.annotation == "GeoIntent"
        assert intent.default == GeoIntent()

    def test_the_model_sees_the_intent_not_the_free_strings(self):
        declaration = FunctionTool(geocode_location)._get_declaration()
        assert declaration is not None and declaration.name == "geocode_location"
        properties = declaration.parameters_json_schema["properties"]
        assert properties["intent"]["$ref"] == "#/$defs/GeoIntent"
        for gone in ("city", "zone", "raw_user_message", "country_code", "country_guess",
                     "tool_context"):
            assert gone not in properties
        assert not declaration.parameters_json_schema.get("required")


# --- the rest of the mapping ---------------------------------------------------


class TestMapping:
    def test_a_city_place_is_the_city(self, core):
        geocode_location(
            intent=GeoIntent(places=[Place(mention="Budapest", kind="city", canonical="Budapest")]),
            tool_context=_ctx("hotel in Budapest"),
        )

        assert core[0]["city"] == "Budapest"
        assert core[0]["zone"] is None

    def test_the_places_own_city_is_used_when_the_user_names_none(self, core):
        intent = GeoIntent(places=[Place(mention="champs élysées", kind="street",
                                         canonical="Champs-Élysées", city="Paris",
                                         city_inferred=True, country="FR")])

        geocode_location(intent=intent, tool_context=_ctx("autour des champs élysées"))

        assert core[0]["zone"] == "Champs-Élysées"
        assert core[0]["city"] == "Paris"
        assert core[0]["country_guess"] == "FR"

    def test_a_city_the_model_put_second_in_places_is_still_the_city(self, core, statuses):
        # Trace A filled another way: the schema lets the model list the city
        # as a place. Reading `places[0]` only would drop Paris and ask which
        # city — the very defect of trace A.
        intent = GeoIntent(places=[
            _station(mention="Gare du nord"),
            Place(mention="paris", kind="city", canonical="Paris", country="FR"),
        ])

        geocode_location(intent=intent, tool_context=_ctx("paris Gare du nord demain"))

        assert core[0]["zone"] == "Gare du Nord"
        assert core[0]["city"] == "Paris"
        assert core[0]["country_guess"] == "FR"

    def test_a_place_the_model_put_after_the_city_is_still_the_zone(self, core):
        # The other order: the station must not be lost to a city-wide search.
        intent = GeoIntent(places=[
            Place(mention="paris", kind="city", canonical="Paris"),
            _station(mention="Gare du nord"),
        ])

        geocode_location(intent=intent, tool_context=_ctx("paris Gare du nord demain"))

        assert core[0]["zone"] == "Gare du Nord"
        assert core[0]["city"] == "Paris"

    def test_a_hotel_is_never_a_zone(self, core):
        intent = GeoIntent(
            places=[Place(mention="Pullman", kind="hotel", canonical="Pullman")],
            city=CityRef(mention="Lyon", canonical="Lyon"),
        )

        geocode_location(intent=intent, tool_context=_ctx("le Pullman à Lyon"))

        assert core[0]["zone"] is None
        assert core[0]["city"] == "Lyon"

    def test_an_empty_intent_carries_the_earlier_destination_over(self, core):
        profile = {"city": "Paris", "zone": "Montmartre", "country_anchor": "FR"}

        geocode_location(intent=GeoIntent(), tool_context=_ctx("moins cher ?", profile_in=profile))

        assert (core[0]["city"], core[0]["zone"], core[0]["country_code"]) == (
            "Paris", "Montmartre", "FR"
        )

    def test_a_named_region_reaches_the_state_tier(self, core):
        intent = GeoIntent(places=[Place(mention="Portland", kind="city", canonical="Portland")],
                           region_named="OR")

        geocode_location(intent=intent, tool_context=_ctx("hotel in Portland or"))

        assert core[0]["region_named"] == "OR"

    def test_homonym_and_too_vague_are_logged_not_mapped(self, core, metric):
        for reason in ("homonym", "too_vague"):
            geocode_location(
                intent=GeoIntent(places=[Place(mention="Victoria", kind="city", canonical="Victoria")],
                                 ambiguity=Ambiguity(reason=reason)),
                tool_context=_ctx("hotel in Victoria"),
            )

        assert [args["city"] for args in core] == ["Victoria", "Victoria"]
        assert [_fields(line)["ambiguity"] for line in metric()] == ["homonym", "too_vague"]


class TestNamedRegionInTheCore:
    def test_a_named_state_qualifies_the_query_the_text_tier_cannot_read(self, monkeypatch):
        # « Portland or »: "or" is a word, so the free-text tier must skip it;
        # the model's extracted region is safe to read.
        v6, _box = _patch(monkeypatch)

        geocode_core(city="Portland", region_named="OR", raw_user_message="hotel in Portland or")

        assert v6.calls[0] == ("Portland, Oregon", None)

    def test_a_named_region_is_ignored_outside_the_us(self, monkeypatch):
        # « Perth WA » is Western Australia, not Washington.
        v6, _box = _patch(monkeypatch)

        geocode_core(city="Perth", region_named="WA", country_guess="AU",
                     raw_user_message="hotel in Perth WA")

        # No state term in the query. The lookup is scoped to the guessed
        # country first (2026-10-27), then retried worldwide since the fake
        # finds nothing there.
        assert v6.calls[:2] == [("Perth", "AU"), ("Perth", None)]


# --- Q14: the city the user wrote beats the place's inferred city ----------------

BRUSSELS = _c("Brussels", "BE", "Brussels-Capital", lat=50.8467, lon=4.3525)
#: The model knows a famous Gare du Nord: it infers Paris (and France) for it.
_PARIS_STATION = Place(mention="Gare du Nord", kind="station", canonical="Gare du Nord",
                       city="Paris", city_inferred=True, country="FR")


@pytest.fixture
def verified(monkeypatch):
    """Spy: every city `_verified_city` is asked to check."""
    asked: list[tuple[str, str]] = []
    real = geocode_tool._verified_city

    def spy(ref, claims, **kwargs):
        asked.append((ref.mention, ref.canonical))
        return real(ref, claims, **kwargs)

    monkeypatch.setattr(geocode_tool, "_verified_city", spy)
    return asked


class TestTheCityTheUserWroteWins:
    def test_gare_du_nord_a_bruxelles_is_searched_in_brussels(
        self, monkeypatch, core, metric, verified
    ):
        # Q07's open point: the station's inferred Paris used to beat the
        # Bruxelles the user wrote. Mapbox (mocked) checks the corrected name.
        v6, _box = _patch(monkeypatch, _V6({"Brussels": [BRUSSELS]}), inventory={50.8467: 40})
        intent = GeoIntent(places=[_PARIS_STATION],
                           city=CityRef(mention="Bruxelles", canonical="Brussels"))

        geocode_location(intent=intent, tool_context=_ctx("Un hôtel Gare du Nord à Bruxelles demain"))

        assert verified == [("Bruxelles", "Brussels")]
        assert v6.calls == [("Brussels", None)]
        assert core[0]["city"] == "Brussels"
        assert core[0]["zone"] == "Gare du Nord"
        # The overruled inference takes its country with it: no FR hint.
        assert core[0]["country_guess"] is None
        line = metric()[0]
        assert _fields(line)["city_conflicts"] == "1"
        # GDPR: a count, never a word of the message.
        for word in ("bruxelles", "brussels", "paris", "gare", "nord", "demain"):
            assert word not in line.lower()

    def test_a_city_place_the_user_wrote_wins_the_same_way(self, core, metric):
        intent = GeoIntent(places=[
            _PARIS_STATION,
            Place(mention="Bruxelles", kind="city", canonical="Bruxelles", country="BE"),
        ])

        geocode_location(intent=intent, tool_context=_ctx("Gare du Nord à Bruxelles"))

        assert (core[0]["city"], core[0]["country_guess"]) == ("Bruxelles", "BE")
        assert _fields(metric()[0])["city_conflicts"] == "1"

    def test_a_city_only_in_the_earlier_request_keeps_the_places_own_city(
        self, core, metric, verified
    ):
        # The answer turn: « Bruxelles » is carried by the concierge's prefix,
        # not written in this reply. The order stays as after Q07.
        prefix = (
            "EARLIER REQUEST (the user's own words, not searched yet): "
            "un hôtel Gare du Nord à Bruxelles\n"
            'YOU ASKED: {"kind": "city_needed", "subject": "Gare du Nord", "options": []}\n'
            "REPLY:"
        )
        intent = GeoIntent(places=[_PARIS_STATION],
                           city=CityRef(mention="Bruxelles", canonical="Bruxelles"))

        geocode_location(intent=intent, tool_context=_ctx(prefix, "demain à 15h"))

        assert core[0]["city"] == "Paris"
        assert core[0]["country_guess"] == "FR"
        assert verified == []
        assert _fields(metric()[0])["city_conflicts"] == "0"

    @pytest.mark.parametrize("written", ["paris", "Paris"])
    def test_the_same_city_written_is_no_conflict(self, core, metric, written):
        intent = GeoIntent(places=[_PARIS_STATION],
                           city=CityRef(mention=written, canonical="Paris"))

        geocode_location(intent=intent, tool_context=_ctx(f"Gare du Nord {written} demain"))

        assert core[0]["city"] == "Paris"
        assert _fields(metric()[0])["city_conflicts"] == "0"

    def test_city_needed_still_drops_every_city(self, core, metric):
        intent = GeoIntent(places=[_PARIS_STATION],
                           city=CityRef(mention="Bruxelles", canonical="Bruxelles"),
                           ambiguity=Ambiguity(reason="city_needed"))

        geocode_location(intent=intent, tool_context=_ctx("Gare du Nord à Bruxelles"))

        assert core[0]["city"] == ""
        assert _fields(metric()[0])["city_conflicts"] == "0"


class TestAPlaceSurvivesAnAddedArticleOrATypo:
    """Q18 (H3): the model writes « les champs élysées » for « des champs
    élysées », or the corrected « près des Champs-Élysées » for a typo."""

    @pytest.mark.parametrize(
        "text, mention, fuzzy",
        [
            # The canonical is in the text, whole words: anchored exactly.
            ("je cherche un hôtel autour des champs élysées", "les champs élysées", "0"),
            ("hotel pres des champ elysee pour demain", "près des Champs-Élysées", "1"),
            ("hotel pres des champ elysee pour demain", "Champs-Élysées", "1"),
        ],
    )
    def test_the_place_is_anchored(self, core, metric, text, mention, fuzzy):
        intent = GeoIntent(
            places=[Place(mention=mention, kind="landmark", canonical="Champs-Élysées")]
        )

        geocode_location(intent=intent, tool_context=_ctx(text))

        assert core[0]["zone"] == "Champs-Élysées"
        fields = _fields(metric()[0])
        assert fields["mentions_discarded"] == "0"
        assert fields["mentions_fuzzy"] == fuzzy

    def test_a_mention_absent_from_the_text_is_anchored_by_its_canonical(self, core, metric):
        intent = GeoIntent(
            places=[Place(mention="les Champs", kind="landmark", canonical="Champs-Élysées")]
        )

        geocode_location(intent=intent, tool_context=_ctx("un hôtel autour des champs elysees"))

        assert core[0]["zone"] == "Champs-Élysées"
        fields = _fields(metric()[0])
        assert fields["mentions_discarded"] == "0"
        assert fields["mentions_fuzzy"] == "0"

    @pytest.mark.parametrize(
        "text, mention",
        [
            ("un hôtel près de la Gare du Nord demain", "Bruxelles"),
            ("un hôtel à Londres demain", "London"),
        ],
    )
    def test_a_city_the_user_never_wrote_is_still_discarded(self, core, metric, text, mention):
        intent = GeoIntent(city=CityRef(mention=mention, canonical=mention))

        geocode_location(intent=intent, tool_context=_ctx(text))

        assert core[0]["city"] == ""
        fields = _fields(metric()[0])
        assert fields["mentions_discarded"] == "1"
        assert fields["mentions_fuzzy"] == "0"

    def test_no_word_of_the_message_is_on_the_line(self, core, metric):
        intent = GeoIntent(
            places=[Place(mention="près des Champs-Élysées", kind="landmark", canonical="Champs-Élysées")]
        )

        geocode_location(
            intent=intent, tool_context=_ctx("hotel pres des champ elysee pour demain")
        )

        [line] = metric()
        assert _fields(line)["mentions_fuzzy"] == "1"
        for word in ("champ", "elysee", "pres", "demain"):
            assert word not in line.lower()


class TestAsksNearby:
    """Prod session 8a6576a4 (2026-10-27): « try a nearby area » after an empty
    Galveston search sent the same intent twice (turns 6 and 8, below), and the
    search ran on the same 20 km disc. `asks_nearby` is what widens it."""

    @pytest.mark.parametrize(
        "intent",
        [
            {"places": [], "city": None, "carryover": "keep", "relation": "near"},
            {"schema_version": "1.1", "places": [], "city": None, "relation": "near", "carryover": "keep"},
        ],
    )
    def test_the_prod_intents_ask_for_a_nearby_area(self, intent):
        assert geocode_tool.asks_nearby(intent) is True

    @pytest.mark.parametrize(
        "intent",
        [
            None,
            {},
            {"places": [], "relation": "in"},
            # « near Galveston » names the place: a city search, not a wider one.
            {"places": [{"mention": "Galveston", "kind": "city", "canonical": "Galveston",
                         "city": None, "country": "US", "postal_code": None}], "relation": "near"},
            {"city": {"mention": "Houston", "canonical": "Houston"}, "relation": "near"},
            # Fails validation: nothing of it is used, as in `geocode_location`.
            {"relation": "near", "unknown": 1},
        ],
    )
    def test_anything_else_does_not(self, intent):
        assert geocode_tool.asks_nearby(intent) is False

    @pytest.mark.parametrize(
        ("intent", "marked"),
        [({"places": [], "city": None, "carryover": "keep", "relation": "near"}, True), ({}, False)],
    )
    def test_the_real_tool_marks_its_result(self, monkeypatch, intent, marked):
        galveston = {"ok": True, "latitude": 29.305554, "longitude": -94.793248,
                     "distance_origin_type": "city_centroid", "profile_delta": {}}
        monkeypatch.setattr(geocode_tool, "geocode_core", lambda **kwargs: dict(galveston))

        result = _run_tool(intent, "try a nearby area", profile_in={"city": "Galveston"})

        assert result.get("nearby", False) is marked

    def test_a_failed_geocode_is_never_marked(self, core):
        intent = {"places": [], "city": None, "relation": "near"}
        assert "nearby" not in _run_tool(intent, "try a nearby area", profile_in={"city": "Galveston"})
