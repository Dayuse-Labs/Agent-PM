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
        assert len(root_agent.tools) == 1
        assert root_agent.tools[0].tool_filter == ALLOWED_MCP_TOOLS


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

    def test_authorization_header_is_the_raw_token_when_set(self, monkeypatch):
        # The MCP_B2C server rejects "Bearer <token>" (observed contract): the
        # raw token IS the header value.
        monkeypatch.setenv("MCP_B2C_AUTH_TOKEN", "tok-123")
        assert build_connection_params().headers["Authorization"] == "tok-123"

    def test_no_authorization_header_when_token_empty(self, monkeypatch):
        # An empty Authorization header is illegal — must be omitted entirely.
        for value in (None, "", "  \n"):
            if value is None:
                monkeypatch.delenv("MCP_B2C_AUTH_TOKEN", raising=False)
            else:
                monkeypatch.setenv("MCP_B2C_AUTH_TOKEN", value)
            assert "Authorization" not in (build_connection_params().headers or {})


class TestModel:
    def test_agent_name(self):
        assert root_agent.name == "hotel_search_agent"

    def test_model_defaults_to_gpt_4o_mini(self, monkeypatch, reload_agent):
        monkeypatch.delenv("DAYUSE_MODEL", raising=False)
        assert reload_agent().root_agent.model.model == "gpt-4o-mini"

    def test_model_is_driven_by_dayuse_model(self, monkeypatch, reload_agent):
        monkeypatch.setenv("DAYUSE_MODEL", "openrouter/some/model")
        assert reload_agent().root_agent.model.model == "openrouter/some/model"
