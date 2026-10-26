"""D7 interim-bearer tests over the real ASGI app (starlette TestClient, offline).

serve.py reads A2A_BEARER_TOKEN at import, so each test imports it fresh with a
controlled environment. No network: the card build at import lists the agent's
tools, which opens a real MCP_B2C session (counted by its rate limit, a timeout
when unreachable) — the `serve` fixture stubs McpToolset.get_tools.
"""
import importlib
import sys

import pytest
from google.adk.tools.mcp_tool import McpToolset
from starlette.testclient import TestClient

TOKEN = "test-token-s1"

SERVE_MODULE = "hotel_search_agent.serve"


def _import_serve_fresh():
    sys.modules.pop(SERVE_MODULE, None)
    return importlib.import_module(SERVE_MODULE)


async def _no_tools(self, readonly_context=None):
    return []


@pytest.fixture
def serve(monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", TOKEN)
    monkeypatch.setattr(McpToolset, "get_tools", _no_tools)
    module = _import_serve_fresh()
    yield module
    sys.modules.pop(SERVE_MODULE, None)


@pytest.fixture
def client(serve):
    with TestClient(serve.app) as test_client:
        yield test_client


class TestFailClosed:
    def test_boot_fails_without_token(self, monkeypatch):
        monkeypatch.delenv("A2A_BEARER_TOKEN", raising=False)
        with pytest.raises(RuntimeError, match="A2A_BEARER_TOKEN"):
            _import_serve_fresh()
        sys.modules.pop(SERVE_MODULE, None)

    def test_boot_fails_with_blank_token(self, monkeypatch):
        monkeypatch.setenv("A2A_BEARER_TOKEN", "   ")
        with pytest.raises(RuntimeError, match="A2A_BEARER_TOKEN"):
            _import_serve_fresh()
        sys.modules.pop(SERVE_MODULE, None)


class TestAgentCardDiscovery:
    def test_card_is_served_without_bearer(self, client):
        response = client.get("/.well-known/agent-card.json")
        assert response.status_code == 200
        card = response.json()
        assert card["name"] == "b2c_hotel_search"

    def test_card_declares_the_interim_bearer_scheme(self, client):
        card = client.get("/.well-known/agent-card.json").json()
        assert "bearer-interim" in card["securitySchemes"]
        assert card["securitySchemes"]["bearer-interim"]["scheme"] == "bearer"
        assert {"bearer-interim": []} in card["security"]


class TestBearerGate:
    def test_401_without_token(self, client):
        response = client.post("/", json={})
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_401_with_wrong_token(self, client):
        response = client.post(
            "/", json={}, headers={"Authorization": "Bearer wrong-token"}
        )
        assert response.status_code == 401

    def test_401_with_malformed_scheme(self, client):
        response = client.post("/", json={}, headers={"Authorization": TOKEN})
        assert response.status_code == 401

    def test_trace_middleware_sits_INSIDE_the_bearer_gate(self, serve):
        """OBS4 ordering lock: `add_middleware` puts the last added outermost,
        so the D7 gate must be added last — an unauthenticated POST has to be
        rejected before `A2aTurnObservation` opens a trace for it."""
        from b2c_common import BearerAuthMiddleware
        from b2c_common.observability import A2aTurnObservation

        assert [middleware.cls for middleware in serve.app.user_middleware] == [
            BearerAuthMiddleware,  # index 0 = outermost
            A2aTurnObservation,
        ]

    def test_good_token_passes_the_gate(self, client):
        # The empty body is not a valid A2A JSON-RPC call — whatever the handler
        # answers, the D7 gate must NOT be the thing rejecting it.
        response = client.post(
            "/", json={}, headers={"Authorization": f"Bearer {TOKEN}"}
        )
        assert response.status_code != 401
