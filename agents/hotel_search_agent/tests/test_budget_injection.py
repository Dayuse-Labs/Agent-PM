"""Offline unit tests for the budget-cap carryover (UX1 follow-up, measured
+ arbitrated by Fabien 2026-08-27).

No network, no LLM, no MCP. `user_content` is built through the REAL ADK
a2a→genai part converter — the same inbound hop `test_occupancy.py` uses —
so the profile is read the same way production reads it.

Mirrors `test_occupancy.py`'s structure: `budget_max` is a scalar carried the
same way `adults`/`children` are, not a set like `amenities`.
"""
from __future__ import annotations

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.genai import types as genai_types

from hotel_search_agent.budget_injection import inject_profile_budget
from hotel_search_agent.response_bridge import positive_budget


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
            genai_types.Part(text="montre m'en d'autres"),
            convert_a2a_part_to_genai_part(datapart),
        ],
    )
    return _Ctx(user_content=content)


class TestPositiveBudget:
    def test_accepts_positive_numbers_and_numeric_strings(self):
        assert positive_budget(80) == 80.0
        assert positive_budget("80") == 80.0
        assert positive_budget(79.99) == 79.99

    def test_rejects_non_positive_and_garbage(self):
        for bad in (None, 0, -10, "beaucoup", [], {}, True):
            assert positive_budget(bad) is None, bad


class TestCarryover:
    def test_profile_fills_the_slot_when_the_model_omits_it(self):
        # The exact gap UX1 measured: turn 1 "max 80 euros", turn 2 "montre
        # m'en d'autres" (no price mentioned) — active_filters kept showing
        # 80.0, but priceRangeMax never reached search_offers.
        args = {"lat": 48.87, "lon": 2.31}
        ctx = _ctx_with_profile(budget_max=80.0)
        assert inject_profile_budget(_Tool("search_offers"), args, ctx) is None
        assert args["priceRangeMax"] == 80.0

    def test_a_fresh_statement_supersedes_the_profile(self):
        # A budget does not accumulate: "max 50" REPLACES 80, never combines.
        args = {"priceRangeMax": 50}
        ctx = _ctx_with_profile(budget_max=80.0)
        inject_profile_budget(_Tool("search_offers"), args, ctx)
        assert args["priceRangeMax"] == 50.0

    def test_model_garbage_falls_back_to_the_profile(self):
        args = {"priceRangeMax": -5}
        ctx = _ctx_with_profile(budget_max=80.0)
        inject_profile_budget(_Tool("search_offers"), args, ctx)
        assert args["priceRangeMax"] == 80.0

    def test_model_garbage_with_no_profile_is_dropped_not_forwarded(self):
        args = {"priceRangeMax": -5}
        inject_profile_budget(_Tool("search_offers"), args, _ctx_with_profile())
        assert "priceRangeMax" not in args

    def test_normalises_the_models_own_value_in_place(self):
        args = {"priceRangeMax": "80"}
        inject_profile_budget(_Tool("search_offers"), args, _ctx_with_profile())
        assert args["priceRangeMax"] == 80.0


class TestNonInvention:
    def test_nothing_stated_anywhere_writes_no_key(self):
        args = {"lat": 48.87, "lon": 2.31}
        inject_profile_budget(_Tool("search_offers"), args, _ctx_with_profile())
        assert "priceRangeMax" not in args
        assert args == {"lat": 48.87, "lon": 2.31}

    def test_a_profile_with_no_budget_invents_nothing(self):
        args = {}
        inject_profile_budget(_Tool("search_offers"), args, _ctx_with_profile(city="Paris"))
        assert args == {}

    def test_missing_or_undecodable_datapart_is_an_honest_no_op(self):
        for content in (None, genai_types.Content(role="user", parts=[])):
            args = {}
            inject_profile_budget(_Tool("search_offers"), args, _Ctx(user_content=content))
            assert args == {}


class TestOtherToolsAreNeverGivenABudget:
    def test_no_carryover_is_injected_into_a_non_search_tool(self):
        args = {"hotelId": 42}
        inject_profile_budget(
            _Tool("get_hotel_details"), args, _ctx_with_profile(budget_max=80.0)
        )
        assert args == {"hotelId": 42}

    def test_a_stray_key_on_another_tool_is_left_alone(self):
        # priceRangeMax is native to search_offers's own schema — unlike the
        # virtual amenities param, it can never appear on another tool's args
        # in the first place, so there is nothing to strip here (contrast
        # with occupancy.py's find_hotel_by_name case).
        args = {"name": "Hilton"}
        inject_profile_budget(
            _Tool("find_hotel_by_name"), args, _ctx_with_profile(budget_max=80.0)
        )
        assert args == {"name": "Hilton"}
