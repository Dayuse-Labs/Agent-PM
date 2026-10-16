"""QA14707 (Q03): the leaf's clarify questions travel as `Clarification` data.

Path under test, end to end and offline: `geocode_core` builds the object,
`capture_after_tool` stashes it, `emit_search_datapart` relays it in the
DataPart, decoded here through the REAL ADK A2A converter (the hop the
concierge relies on). The fakes stand in for Mapbox and the inventory only.

What these tests pin is the "no invented option" half of the leaf: the options
are exactly the candidates the resolver kept, and the text of the question is
the one the leaf already sent (the current concierge ignores the new key).
"""
from __future__ import annotations

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_genai_part_to_a2a_part

from b2c_common.clarification import Clarification
from hotel_search_agent import geo_resolver, geocode_tool
from hotel_search_agent.contract import SearchResponse
from hotel_search_agent.geocode_tool import geocode_core
from hotel_search_agent.mapbox_client import GeocodeCandidate
from hotel_search_agent.response_bridge import capture_after_tool, emit_search_datapart


def _c(name, cc, region, *, rank, lat, lon=0.0):
    return GeocodeCandidate(
        latitude=lat,
        longitude=lon,
        name=name,
        place_name=f"{name}, {region}, {cc}",
        place_formatted=f"{region}, {cc}",
        feature_type="place",
        country_code=cc,
        region=region,
        bbox=None,
        rank=rank,
    )


class _V6:
    def __init__(self, candidates):
        self.candidates = candidates

    def geocode_candidates(self, query, **kwargs):
        return list(self.candidates)


class _SearchBox:
    def __init__(self):
        self.calls = 0

    def forward_candidates(self, query, **kwargs):
        self.calls += 1
        return []


class _Inventory:
    def __init__(self, by_lat):
        self.by_lat = by_lat

    def count_near(self, lat, lon, *, radius_km=25.0):
        return self.by_lat.get(round(lat, 4), 0)


class _Ctx:
    def __init__(self):
        self.state: dict = {}
        self.user_content = None


class _Tool:
    def __init__(self, name):
        self.name = name


def _patch(monkeypatch, candidates, inventory):
    inv = _Inventory(inventory)
    box = _SearchBox()
    monkeypatch.setattr(geocode_tool, "get_mapbox_client", lambda: _V6(candidates))
    monkeypatch.setattr(geocode_tool, "get_inventory", lambda: inv)
    monkeypatch.setattr(geocode_tool, "get_searchbox_client", lambda: box)
    return inv, box


def _through_the_leaf(result: dict) -> tuple[dict, str]:
    """The tool response as the concierge receives it: (DataPart, text)."""
    ctx = _Ctx()
    assert capture_after_tool(_Tool("geocode_location"), {}, ctx, result) is None
    content = emit_search_datapart(ctx)
    assert content is not None
    data = None
    for part in content.parts:
        if part.inline_data is not None:
            a2a_part = convert_genai_part_to_a2a_part(part)
            assert isinstance(a2a_part.root, a2a_types.DataPart)
            data = a2a_part.root.data
    assert data is not None, "no DataPart in the leaf's event"
    text = "".join(p.text for p in content.parts if p.text)
    return data, text


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


# Victoria BC and Victoria TX: a genuine homonym, both with a real inventory.
# Two candidates the resolver must NOT offer: a micro-homonym outside the
# inventory tier (1 hotel), and the same BC place expressed a second time.
_BC = _c("Victoria", "CA", "British Columbia", rank=0, lat=48.43)
_TX = _c("Victoria", "US", "Texas", rank=1, lat=28.80)
_MICRO = _c("Victoria", "AU", "Victoria", rank=2, lat=-37.47)
_BC_AGAIN = _c("Victoria", "CA", "British Columbia", rank=3, lat=48.50)
_HOMONYMS = [_BC, _TX, _MICRO, _BC_AGAIN]
_HOMONYM_INVENTORY = {48.43: 20, 28.80: 15, -37.47: 1, 48.5: 20}


class TestCityNeeded:
    def test_the_question_rides_in_the_datapart_with_no_option(self, monkeypatch):
        _, box = _patch(monkeypatch, [], {})
        statuses: list[str] = []
        monkeypatch.setattr(
            geocode_tool, "mark_level", lambda level, status_message="": statuses.append(status_message)
        )

        result = geocode_core(
            zone="Gare du Nord", locale="fr-FR", raw_user_message="un hôtel près de Gare du Nord demain"
        )

        # The source of the question is unchanged: a `geocode_ambiguous` error
        # whose status is `geocode_city_needed`, asked before any lookup.
        assert statuses == ["geocode_city_needed"]
        assert result["error"] == "geocode_ambiguous"
        assert result["diagnostics"]["options"] == []
        assert box.calls == 0
        data, text = _through_the_leaf(result)

        assert Clarification.model_validate(data["clarification"]) == Clarification(
            kind="city_needed", subject="Gare du Nord", options=[]
        )
        assert data["requires_clarification"] is True
        # The leaf's text is the question it always sent, word for word.
        assert text == result["diagnostics"]["question"]

    def test_the_answer_turn_still_gets_the_zone(self, monkeypatch):
        # Persisting the subject (2026-08-26) is untouched by the new object.
        _patch(monkeypatch, [], {})

        result = geocode_core(zone="Gare du Nord", raw_user_message="near Gare du Nord")
        data, _ = _through_the_leaf(result)

        assert data["profile_delta"]["zone"] == {"op": "set", "value": "Gare du Nord"}


class TestHomonym:
    def test_the_options_are_exactly_the_candidates_the_resolver_kept(self, monkeypatch):
        inv, _ = _patch(monkeypatch, _HOMONYMS, _HOMONYM_INVENTORY)

        result = geocode_core(city="Victoria", raw_user_message="hotel in Victoria")
        data, _ = _through_the_leaf(result)

        clarification = Clarification.model_validate(data["clarification"])
        assert clarification.kind == "homonym"
        assert clarification.subject == "Victoria"
        assert [(o.city, o.region, o.country_code) for o in clarification.options] == [
            ("Victoria", "British Columbia", "CA"),
            ("Victoria", "Texas", "US"),
        ]
        # Same list, same order as the resolver's own decision on these
        # candidates: nothing added, nothing dropped, nothing reordered.
        kept = geo_resolver.resolve(_HOMONYMS, inventory=inv, requested_name="Victoria").options
        assert [(o.region, o.country_code) for o in clarification.options] == [
            (k.region, k.country_code) for k in kept
        ]

    def test_each_option_reads_as_it_does_in_the_question(self, monkeypatch):
        _patch(monkeypatch, _HOMONYMS, _HOMONYM_INVENTORY)

        result = geocode_core(city="Victoria", raw_user_message="hotel in Victoria")
        data, text = _through_the_leaf(result)

        labels = [o["label"] for o in data["clarification"]["options"]]
        assert labels == ["Victoria (British Columbia, CA)", "Victoria (Texas, US)"]
        assert all(label in result["diagnostics"]["question"] for label in labels)
        assert text == result["diagnostics"]["question"]

    def test_a_nameless_candidate_is_left_out_and_every_label_is_in_the_question(self):
        # Mapbox can return a feature with no `name` (only a context and a
        # `place_name`). The question prints it as a bare context: it has no
        # city to answer with, so it is not offered — and every label that IS
        # offered stays verbatim in the question.
        nameless = _c("", "CA", "British Columbia", rank=4, lat=48.6)
        kept = [_BC, nameless, _TX]

        clarification = geocode_tool._homonym_clarification("Victoria", kept)

        assert clarification is not None
        assert [o.country_code for o in clarification.options] == ["CA", "US"]
        question = geo_resolver._clarify_question(kept)
        assert all(o.label in question for o in clarification.options)
        assert geocode_tool._homonym_clarification("Victoria", [nameless]) is None

    def test_a_homonym_asked_after_tier_two_missed_also_carries_its_options(self, monkeypatch):
        # The clarify with a zone in hand (`geocode_tool`, after the Search-Box
        # tier misses) is the second source of the same question.
        _, box = _patch(monkeypatch, _HOMONYMS, _HOMONYM_INVENTORY)

        result = geocode_core(
            city="Victoria", zone="Chinatown", raw_user_message="hotel near Chinatown in Victoria"
        )

        assert result["error"] == "geocode_ambiguous"
        assert box.calls == 1
        data, _ = _through_the_leaf(result)
        clarification = Clarification.model_validate(data["clarification"])
        assert clarification.subject == "Victoria"
        assert {o.country_code for o in clarification.options} == {"CA", "US"}

    def test_the_question_holds_no_coordinate(self, monkeypatch):
        _patch(monkeypatch, _HOMONYMS, _HOMONYM_INVENTORY)

        data, _ = _through_the_leaf(
            geocode_core(city="Victoria", raw_user_message="hotel in Victoria")
        )

        assert not _keys(data["clarification"]) & {"latitude", "longitude", "lat", "lon", "bbox"}

    def test_the_concierge_contract_reads_the_relayed_object(self, monkeypatch):
        _patch(monkeypatch, _HOMONYMS, _HOMONYM_INVENTORY)

        data, _ = _through_the_leaf(
            geocode_core(city="Victoria", raw_user_message="hotel in Victoria")
        )

        response = SearchResponse.model_validate({"clarification": data["clarification"]})
        assert response.clarification is not None
        assert len(response.clarification.options) == 2


class TestRelay:
    def test_an_off_contract_object_is_dropped_and_the_question_still_goes_out(self):
        # A coordinate slipped into an option: the object is refused at the
        # leaf's edge, the turn keeps its text question and its flag.
        question = "Did you mean Victoria (British Columbia, CA), or Victoria (Texas, US)?"
        bad = {
            "ok": False,
            "error": "geocode_ambiguous",
            "diagnostics": {"question": question, "options": []},
            "clarification": {
                "kind": "homonym",
                "subject": "Victoria",
                "options": [{"label": "Victoria", "city": "Victoria", "latitude": 48.43}],
            },
        }

        data, text = _through_the_leaf(bad)

        assert "clarification" not in data
        assert data["requires_clarification"] is True
        assert text == question

    def test_a_later_clarify_without_an_object_clears_the_earlier_one(self):
        ctx = _Ctx()
        first = {
            "ok": False,
            "error": "geocode_ambiguous",
            "diagnostics": {"question": "Near « Gare du Nord » — which city?", "options": []},
            "clarification": {"kind": "city_needed", "subject": "Gare du Nord"},
        }
        second = {"ok": False, "error": "geocode_ambiguous", "diagnostics": {"question": "Which one?"}}

        capture_after_tool(_Tool("geocode_location"), {}, ctx, first)
        capture_after_tool(_Tool("geocode_location"), {}, ctx, second)
        content = emit_search_datapart(ctx)

        a2a_part = convert_genai_part_to_a2a_part(content.parts[-1])
        assert "clarification" not in a2a_part.root.data

    def test_a_clarify_followed_by_a_search_asked_nothing(self):
        ctx = _Ctx()
        capture_after_tool(
            _Tool("geocode_location"),
            {},
            ctx,
            {
                "ok": False,
                "error": "geocode_ambiguous",
                "diagnostics": {"question": "Near « Gare du Nord » — which city?", "options": []},
                "clarification": {"kind": "city_needed", "subject": "Gare du Nord"},
            },
        )
        ctx.state["temp:hotel_search_results"] = [{"id": 1, "name": "Hotel A"}]

        content = emit_search_datapart(ctx)

        a2a_part = convert_genai_part_to_a2a_part(content.parts[-1])
        assert "clarification" not in a2a_part.root.data
        assert "requires_clarification" not in a2a_part.root.data

    def test_a_successful_geocode_carries_no_question(self, monkeypatch):
        _patch(monkeypatch, [_BC], {48.43: 20})

        result = geocode_core(city="Victoria", raw_user_message="hotel in Victoria")

        assert result["ok"] is True
        assert "clarification" not in result
