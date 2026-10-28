"""Unit tests for hotel_search_agent's wiring — no network, no API key.

Importing root_agent builds the LiteLlm object and constructs the McpToolset,
but the MCP connection is lazy (opened on first tool call), so import stays
offline. These tests pin the allowlist (the security-critical part: the same
MCP_B2C server exposes 4 other tools that belong to other components) and the
env-driven knobs (model slug, MCP url/token/timeout).
"""
import importlib

import pytest

import hotel_search_agent.agent as agent_module
from hotel_search_agent.agent import (
    ALLOWED_MCP_TOOLS,
    build_connection_params,
    root_agent,
)
from hotel_search_agent.geocode_tool import geocode_location

EXPECTED_ALLOWLIST = ["search_offers", "find_hotel_by_name"]

# The 4 other MCP_B2C tools — reachable only from faq-agent / the orchestrator's
# inline tools, never from this leaf.
FORBIDDEN_TOOLS = {
    "get_faq_conditions",
    "generate_booking_link",
    "get_hotel_details",
    "compare_hotels",
}


@pytest.fixture
def reload_agent(monkeypatch, request):
    """Reload the agent module after env tweaks; restore the pristine module afterwards."""

    def _restore():
        monkeypatch.undo()
        importlib.reload(agent_module)

    request.addfinalizer(_restore)
    return lambda: importlib.reload(agent_module)


class TestToolAllowlist:
    def test_allowlist_is_exactly_the_search_surface(self):
        assert ALLOWED_MCP_TOOLS == EXPECTED_ALLOWLIST

    def test_no_forbidden_tool_in_allowlist(self):
        assert FORBIDDEN_TOOLS & set(ALLOWED_MCP_TOOLS) == set()

    def test_toolset_is_built_with_the_allowlist(self):
        # S4: the McpToolset (MCP_B2C) plus the code-owned geocode_location tool.
        assert len(root_agent.tools) == 2
        assert root_agent.tools[0].tool_filter == ALLOWED_MCP_TOOLS
        assert root_agent.tools[1] is geocode_location


class TestMcpConnection:
    def test_timeout_defaults_to_5_seconds(self, monkeypatch):
        monkeypatch.delenv("HOTEL_SEARCH_MCP_TIMEOUT_SECONDS", raising=False)
        assert build_connection_params().timeout == 5.0

    def test_timeout_env_override(self, monkeypatch):
        monkeypatch.setenv("HOTEL_SEARCH_MCP_TIMEOUT_SECONDS", "2.5")
        assert build_connection_params().timeout == 2.5

    def test_url_comes_from_env(self, monkeypatch):
        monkeypatch.setenv("MCP_B2C_URL", "https://mcp-b2c.example.internal/mcp")
        assert build_connection_params().url == "https://mcp-b2c.example.internal/mcp"

    def test_authorization_header_is_a_standard_bearer(self, monkeypatch):
        # RFC 6750 Bearer — accepted server-side since the 2026-07-17 MCP fix.
        monkeypatch.setenv("MCP_B2C_AUTH_TOKEN", "tok-123")
        assert build_connection_params().headers["Authorization"] == "Bearer tok-123"

    def test_no_authorization_header_when_token_empty(self, monkeypatch):
        # An empty Authorization header is illegal — must be omitted entirely.
        for value in (None, "", "  \n"):
            if value is None:
                monkeypatch.delenv("MCP_B2C_AUTH_TOKEN", raising=False)
            else:
                monkeypatch.setenv("MCP_B2C_AUTH_TOKEN", value)
            assert "Authorization" not in (build_connection_params().headers or {})


class TestModel:
    def test_agent_name_is_the_metrics_service_label(self):
        # The ADK agent name feeds `service` in llm_metric_events — b2c_ prefixed
        # to distinguish B2C rows from fleet rows in the shared Postgres (S3).
        assert root_agent.name == "b2c_hotel_search"

    def test_the_leaf_model_sees_only_the_current_turn(self):
        # Stateless invariant, enforced (latency audit 2026-07-28): cross-turn
        # state travels in profile_in — without 'none', an A2A caller reusing
        # a contextId regrows the prompt with the whole session history.
        assert root_agent.include_contents == "none"

    def test_model_defaults_to_gpt_6_luna_with_tool_calling_params(self, monkeypatch, reload_agent):
        monkeypatch.delenv("DAYUSE_MODEL", raising=False)
        monkeypatch.delenv("DAYUSE_REASONING_EFFORT", raising=False)
        model = reload_agent().root_agent.model
        assert model.model == "openai/gpt-6-luna"
        # Without effort "none", OpenAI rejects every tool call of gpt-6-luna on
        # chat completions (probed 2026-10-15); litellm needs the whitelist.
        assert model._additional_args == {
            "reasoning_effort": "none",
            "allowed_openai_params": ["reasoning_effort"],
        }

    def test_gpt_4o_mini_gets_no_reasoning_params(self, monkeypatch, reload_agent):
        monkeypatch.setenv("DAYUSE_MODEL", "gpt-4o-mini")
        monkeypatch.setenv("DAYUSE_REASONING_EFFORT", "low")
        assert reload_agent().root_agent.model._additional_args == {}

    def test_model_is_driven_by_dayuse_model(self, monkeypatch, reload_agent):
        monkeypatch.setenv("DAYUSE_MODEL", "openrouter/some/model")
        assert reload_agent().root_agent.model.model == "openrouter/some/model"


class TestMetricsWiring:
    """S3: the lib's day-1 metrics callbacks + tool budget are wired; model
    switching stays OFF (B2C serves the public)."""

    @staticmethod
    def _as_list(value):
        return value if isinstance(value, list) else [value]

    def test_llm_callbacks_wired(self):
        from dayuse_agent_common import llm_error_metric, llm_timing_after, llm_timing_before

        from hotel_search_agent.equipment_ids import inject_amenities_declaration
        from hotel_search_agent.response_bridge import skip_final_generation

        before = self._as_list(root_agent.before_model_callback)
        assert llm_timing_before in before
        # skip_final_generation stays FIRST: its short-circuit correctly skips
        # the amenity declaration injection along with the model call.
        assert before[0] is skip_final_generation
        assert inject_amenities_declaration in before
        assert llm_timing_after in self._as_list(root_agent.after_model_callback)
        assert llm_error_metric in self._as_list(root_agent.on_model_error_callback)

    def test_tool_callbacks_wired_with_budget(self):
        from dayuse_agent_common import tool_error_metric, tool_timing_after, tool_timing_before

        from hotel_search_agent.mcp_guard import (
            mcp_circuit_after_tool,
            mcp_circuit_before_tool,
            mcp_circuit_on_error,
        )

        from hotel_search_agent.datetime_resolver import (
            resolve_search_date,
            resolve_search_timeslot,
        )
        from hotel_search_agent.budget_injection import inject_profile_budget
        from hotel_search_agent.equipment_ids import enforce_equipment_filters
        from hotel_search_agent.geocode_tool import inject_profile_geo_context
        from hotel_search_agent.occupancy import inject_profile_occupancy
        from hotel_search_agent.schema_guard import drop_args_outside_schema
        from hotel_search_agent.standing import enforce_standing
        from hotel_search_agent.response_bridge import (
            capture_after_tool,
            inject_landmark_radius,
            inject_pagination_offset,
        )

        before = self._as_list(root_agent.before_tool_callback)
        # timing FIRST (budget short-circuits the rest of the list), budget
        # second, the MCP circuit guard (S4) third, then the 7 args-mutating
        # bridges LAST (S-G5/S-G6/P0-1/P0-2/UX1-followup) — each only runs
        # when the call proceeds, order among them is immaterial (disjoint
        # tool names/keys), EXCEPT that inject_landmark_radius must follow
        # the geocode's after_tool stash, which it does by construction
        # (different phase).
        from hotel_search_agent.named_hotel import follow_named_hotel, prepare_named_hotel_lookup

        from hotel_search_agent.relaxation import (
            apply_relax_request,
            read_relax_request,
            rescue_empty_search_after_tool,
        )

        assert before[0] is tool_timing_before
        assert len(before) == 16
        # mcp-dayuse#7: the named-hotel lookup's virtual `date` label is
        # popped before the schema guard would drop it.
        assert before[-3] is prepare_named_hotel_lookup
        # Point 3: the request to loosen the search reads the virtual params
        # before anything else, and applies once every other writer has run.
        assert before[3] is read_relax_request
        assert before[-2] is apply_relax_request
        # mcp-dayuse#8: the schema guard must see the args every other
        # callback has finished rewriting.
        assert before[-1] is drop_args_outside_schema
        assert resolve_search_date in before
        assert resolve_search_timeslot in before
        assert before[2] is mcp_circuit_before_tool
        assert before[4] is enforce_equipment_filters
        assert before[5] is enforce_standing
        assert before[6] is inject_profile_occupancy
        assert before[7] is inject_profile_budget
        assert before[8] is inject_profile_geo_context
        assert before[9] is inject_pagination_offset
        assert before[10] is inject_landmark_radius
        after = self._as_list(root_agent.after_tool_callback)
        # The rescue sees the next-day probe's outcome and runs before the
        # completion (which stands down after it) and the capture.
        from hotel_search_agent.completion import complete_thin_search_after_tool
        from hotel_search_agent.datetime_resolver import probe_next_day_after_tool

        assert after.index(probe_next_day_after_tool) < after.index(rescue_empty_search_after_tool)
        assert after.index(rescue_empty_search_after_tool) < after.index(complete_thin_search_after_tool)
        # The dated search around a found hotel must stash its cards before
        # capture_after_tool would stash the bare identity card.
        assert after.index(follow_named_hotel) == after.index(capture_after_tool) - 1
        assert tool_timing_after in self._as_list(root_agent.after_tool_callback)
        assert mcp_circuit_after_tool in self._as_list(root_agent.after_tool_callback)
        assert tool_error_metric in self._as_list(root_agent.on_tool_error_callback)
        assert mcp_circuit_on_error in self._as_list(root_agent.on_tool_error_callback)

    def test_no_model_switch_callback(self):
        # A per-request MODEL: override must never be honored on public traffic.
        from dayuse_agent_common import switch_model_callback

        assert switch_model_callback not in self._as_list(root_agent.before_model_callback)

    def test_turn_total_instrumentation_wired(self):
        # S-G4: stamp_turn_start (before_agent) feeds the leaf_turn_total ms
        # emit_search_datapart (after_agent) logs — the 4th per-phase counter
        # alongside geocode/MCP (tool_call) and the reasoning pass (llm_call).
        from hotel_search_agent.response_bridge import emit_search_datapart, stamp_turn_start

        assert stamp_turn_start in self._as_list(root_agent.before_agent_callback)
        assert emit_search_datapart in self._as_list(root_agent.after_agent_callback)

    def test_langfuse_leaf_turn_stamp_wired(self):
        # OBS4: feeds the leaf's root observation (opened by
        # A2aTurnObservation in serve.py) its input, and the session id that
        # keeps a directly-called leaf in the Langfuse Sessions view.
        from b2c_common.observability import stamp_a2a_turn

        assert stamp_a2a_turn in self._as_list(root_agent.before_agent_callback)


class TestAmenityInstruction:
    """The closed key list the INSTRUCTION offers the model must be exactly the
    table the enforcement callback can honor — locks instruction<->enum drift."""

    def test_instruction_lists_exactly_the_closed_amenity_keys(self):
        from hotel_search_agent.agent import INSTRUCTION
        from hotel_search_agent.equipment_ids import EQUIPMENT_IDS

        for key in EQUIPMENT_IDS:
            assert key in INSTRUCTION
        assert "{amenity_keys}" not in INSTRUCTION  # .format really ran
        assert "hotelEquipmentIds" in INSTRUCTION  # the prohibition is spelled out



class TestLandmarkInstruction:
    def test_a_short_famous_landmark_is_passed_by_its_full_name(self):
        # mcp-dayuse#7: « St Paul's » resolved to a St Paul's on Burdett Rd (E3),
        # not the cathedral; « St Paul's Cathedral » resolves exactly.
        # QA14707 (Q07): the full name is now the place's `canonical` in the
        # `GeoIntent`, the user's short form its `mention`.
        from hotel_search_agent.agent import INSTRUCTION

        flat = " ".join(INSTRUCTION.split())
        assert 'mention "St Paul\'s", canonical "St Paul\'s Cathedral", city "London"' in flat


class TestGeoIntentInstruction:
    """QA14707 (Q07): the place section of the prompt fills a `GeoIntent`."""

    def test_the_s5_rule_is_the_city_needed_flag_not_a_blank_city(self):
        # DQ6: « gare de Lyon » still makes the code ask which city, but the
        # model now FLAGS it instead of being told to leave a string blank.
        from hotel_search_agent.agent import INSTRUCTION

        flat = " ".join(INSTRUCTION.split())
        assert "leave `city` blank" not in flat
        s5 = flat.index("NAMED AFTER A CITY IT IS NOT IN")
        assert '`ambiguity.reason` to "city_needed" and give no city' in flat[s5:s5 + 400]

    def test_a_written_postcode_goes_in_the_places_postal_code(self):
        # Q23: also when the postcode alone is the place (« dans le 75009 »),
        # which the Q08 postcode path resolves. The S5 bullet stays as it was
        # (Q25 removed the Gare du Nord null case).
        from hotel_search_agent.agent import INSTRUCTION

        flat = " ".join(INSTRUCTION.split())
        assert "A postcode the user writes goes in that place's `postal_code`" in flat
        assert 'also when the postcode alone is the place ("dans le 75009"' in flat
        assert '("Gare du Nord": Paris, Brussels)' not in flat  # Q25 (DQ12)
        assert "A place NAMED AFTER A CITY IT IS NOT IN" in flat

    def test_the_tool_takes_an_intent_not_free_strings(self):
        from hotel_search_agent.agent import INSTRUCTION

        flat = " ".join(INSTRUCTION.split())
        assert "geocode_location with `intent`" in flat
        for gone in ("raw user message", "`country_guess`", "in `zone`", "`country_code`"):
            assert gone not in flat

    def test_the_concierge_clarification_key_is_documented_as_data(self):
        # Decision on Q04's new key: the leaf's model reads it, never copies it.
        from hotel_search_agent.agent import INSTRUCTION

        start = INSTRUCTION.index("`query_params.clarification`")
        rule = " ".join(INSTRUCTION[start:start + 600].split())
        assert "Read it as data" in rule
        assert "never copy it" in rule
        assert "into a tool argument" in rule
