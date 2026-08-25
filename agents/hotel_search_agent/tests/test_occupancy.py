"""Offline unit tests for the party-size carryover and capture (P0-1).

No network, no LLM, no MCP. `user_content` is built through the REAL ADK
a2a→genai part converter — the exact inbound hop that wraps the orchestrator's
DataPart — so the profile is read the same way production reads it.

The behaviour under test is the narrow one the OBS6 baseline actually measured
as broken (`AUDIT-AGENTIQUE-2026-07-30.md` §2 + the measured correction in
HANDOFF): the model already emits `adults`/`children` ~78 % of the turns they
are stated, so these tests are about the three things that were at 0 % —
capturing that emission, remembering it, and re-injecting it next turn — plus
the invariant that matters most, never inventing one.
"""
from __future__ import annotations

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types as genai_types

from hotel_search_agent.occupancy import inject_profile_occupancy
from hotel_search_agent.response_bridge import occupancy_from_args, party_count


class _Ctx:
    def __init__(self, state=None, user_content=None):
        self.state = state if state is not None else {}
        self.user_content = user_content


class _Tool:
    def __init__(self, name):
        self.name = name


def _ctx_with_profile(**profile) -> _Ctx:
    datapart = a2a_types.Part(
        root=a2a_types.DataPart(data={"query_params": {}, "profile_in": dict(profile)})
    )
    content = genai_types.Content(
        role="user",
        parts=[
            genai_types.Part(text="moins cher"),
            convert_a2a_part_to_genai_part(datapart),
        ],
    )
    return _Ctx(user_content=content)


class TestPartyCount:
    def test_accepts_ints_and_integral_strings(self):
        assert party_count(2) == 2
        assert party_count("3") == 3
        assert party_count(" 4 ") == 4
        assert party_count(2.0) == 2
        assert party_count(0) == 0

    def test_rejects_nonsense(self):
        for bad in (None, True, False, "two", "", "2.5", 2.5, -1, 31, [], {}):
            assert party_count(bad) is None, bad

    def test_absurd_party_is_refused_rather_than_searched(self):
        # A fat-fingered "200 adults" would come back as empty inventory and
        # read like a real no-availability answer. Refuse the filter instead.
        assert party_count(200) is None
        assert party_count(30) == 30


class TestCaptureFromArgs:
    def test_captures_what_the_model_emitted(self):
        assert occupancy_from_args({"adults": 2, "children": 1}) == {"adults": 2, "children": 1}

    def test_normalises_integral_strings(self):
        assert occupancy_from_args({"adults": "2"}) == {"adults": 2}

    def test_children_zero_is_a_real_statement(self):
        # "adults only" is information; it must survive to the profile.
        assert occupancy_from_args({"adults": 2, "children": 0}) == {"adults": 2, "children": 0}

    def test_adults_zero_is_not_a_search(self):
        assert occupancy_from_args({"adults": 0}) == {}

    def test_absent_or_garbage_yields_no_key_never_a_wrong_one(self):
        assert occupancy_from_args({}) == {}
        assert occupancy_from_args({"adults": "beaucoup", "children": None}) == {}
        assert occupancy_from_args({"priceRangeMax": 90}) == {}


class TestCarryover:
    def test_profile_fills_the_slot_when_the_model_omits_it(self):
        # The bug this whole change exists for: turn 2 ("moins cher") used to
        # drop the party size and offer rooms the family cannot book.
        args = {"latitude": 48.87, "longitude": 2.31}
        ctx = _ctx_with_profile(adults=2, children=1)
        assert inject_profile_occupancy(_Tool("search_offers"), args, ctx) is None
        assert args["adults"] == 2
        assert args["children"] == 1

    def test_a_fresh_statement_supersedes_the_profile(self):
        # Party size does not accumulate: "actually just me" must REPLACE 2
        # adults, not union with them (the date rule, not the amenities rule).
        args = {"adults": 1}
        ctx = _ctx_with_profile(adults=2, children=1)
        inject_profile_occupancy(_Tool("search_offers"), args, ctx)
        assert args["adults"] == 1
        # children was not restated this turn, so it still carries forward
        assert args["children"] == 1

    def test_model_garbage_falls_back_to_the_profile(self):
        args = {"adults": "plusieurs"}
        ctx = _ctx_with_profile(adults=3)
        inject_profile_occupancy(_Tool("search_offers"), args, ctx)
        assert args["adults"] == 3

    def test_model_garbage_with_no_profile_is_dropped_not_forwarded(self):
        args = {"adults": "plusieurs", "children": -2}
        inject_profile_occupancy(_Tool("search_offers"), args, _ctx_with_profile())
        assert "adults" not in args
        assert "children" not in args

    def test_normalises_the_models_own_value_in_place(self):
        args = {"adults": "2"}
        inject_profile_occupancy(_Tool("search_offers"), args, _ctx_with_profile())
        assert args["adults"] == 2


class TestNonInvention:
    def test_nothing_stated_anywhere_writes_no_key(self):
        # THE invariant. search_offers reads these as MINIMUM-capacity filters,
        # so a guessed adults=1 silently hides inventory nobody excluded.
        args = {"latitude": 48.87, "longitude": 2.31}
        inject_profile_occupancy(_Tool("search_offers"), args, _ctx_with_profile())
        assert "adults" not in args
        assert "children" not in args
        assert args == {"latitude": 48.87, "longitude": 2.31}

    def test_a_profile_with_no_occupancy_invents_nothing(self):
        args = {}
        inject_profile_occupancy(_Tool("search_offers"), args, _ctx_with_profile(city="Paris"))
        assert args == {}

    def test_missing_or_undecodable_datapart_is_an_honest_no_op(self):
        for content in (None, genai_types.Content(role="user", parts=[])):
            args = {}
            inject_profile_occupancy(
                _Tool("search_offers"), args, _Ctx(user_content=content)
            )
            assert args == {}


class TestOtherToolsAreNeverGivenOccupancy:
    def test_find_hotel_by_name_gets_it_stripped(self):
        # additionalProperties:false — a stray key is an MCP rejection, so it is
        # dropped rather than forwarded, even when the profile has one.
        args = {"name": "Hilton", "adults": 2}
        inject_profile_occupancy(
            _Tool("find_hotel_by_name"), args, _ctx_with_profile(adults=2, children=1)
        )
        assert args == {"name": "Hilton"}

    def test_no_carryover_is_injected_into_a_non_search_tool(self):
        args = {"hotel_id": 42}
        inject_profile_occupancy(
            _Tool("get_hotel_details"), args, _ctx_with_profile(adults=2, children=1)
        )
        assert args == {"hotel_id": 42}
