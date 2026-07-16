"""D7 interim-bearer tests over the real ASGI app (starlette TestClient, offline).

serve.py reads A2A_BEARER_TOKEN at import, so each test imports it fresh with a
controlled environment. No network: the agent card is built locally and the MCP
connection attempt during card build fails instantly and gracefully.
"""
import importlib
import sys

import pytest
from starlette.testclient import TestClient

TOKEN = "test-token-s1"


def _import_serve_fresh():
    sys.modules.pop("serve", None)
    return importlib.import_module("serve")


@pytest.fixture
def serve(monkeypatch):
    monkeypatch.setenv("A2A_BEARER_TOKEN", TOKEN)
    module = _import_serve_fresh()
    yield module
    sys.modules.pop("serve", None)


@pytest.fixture
def client(serve):
    with TestClient(serve.app) as test_client:
        yield test_client


class TestFailClosed:
    def test_boot_fails_without_token(self, monkeypatch):
        monkeypatch.delenv("A2A_BEARER_TOKEN", raising=False)
        with pytest.raises(RuntimeError, match="A2A_BEARER_TOKEN"):
            _import_serve_fresh()
        sys.modules.pop("serve", None)

    def test_boot_fails_with_blank_token(self, monkeypatch):
        monkeypatch.setenv("A2A_BEARER_TOKEN", "   ")
        with pytest.raises(RuntimeError, match="A2A_BEARER_TOKEN"):
            _import_serve_fresh()
        sys.modules.pop("serve", None)


class TestAgentCardDiscovery:
    def test_card_is_served_without_bearer(self, client):
        response = client.get("/.well-known/agent-card.json")
        assert response.status_code == 200
        card = response.json()
        assert card["name"] == "hotel_search_agent"

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

    def test_good_token_passes_the_gate(self, client):
        # The empty body is not a valid A2A JSON-RPC call — whatever the handler
        # answers, the D7 gate must NOT be the thing rejecting it.
        response = client.post(
            "/", json={}, headers={"Authorization": f"Bearer {TOKEN}"}
        )
        assert response.status_code != 401
