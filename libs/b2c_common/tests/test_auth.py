"""Unit tests of the consolidated D7 gate (the 3 services' serve-auth suites test the wiring)."""
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from b2c_common.auth import AGENT_CARD_PATH, BearerAuthMiddleware, require_bearer_token

TOKEN = "tok-b2c-common"


def _app() -> TestClient:
    async def ok(request):
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", ok), Route(AGENT_CARD_PATH, ok)])
    app.add_middleware(BearerAuthMiddleware, token=TOKEN)
    return TestClient(app)


class TestRequireBearerToken:
    def test_returns_stripped_token(self, monkeypatch):
        monkeypatch.setenv("A2A_BEARER_TOKEN", "  tok \n")
        assert require_bearer_token() == "tok"

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_fails_closed(self, monkeypatch, value):
        if value is None:
            monkeypatch.delenv("A2A_BEARER_TOKEN", raising=False)
        else:
            monkeypatch.setenv("A2A_BEARER_TOKEN", value)
        with pytest.raises(RuntimeError, match="A2A_BEARER_TOKEN"):
            require_bearer_token()

    def test_custom_env_var(self, monkeypatch):
        monkeypatch.delenv("OTHER_TOKEN", raising=False)
        with pytest.raises(RuntimeError, match="OTHER_TOKEN"):
            require_bearer_token("OTHER_TOKEN")


class TestBearerAuthMiddleware:
    def test_card_open_without_bearer(self):
        assert _app().get(AGENT_CARD_PATH).status_code == 200

    def test_401_without_token(self):
        response = _app().get("/")
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_401_with_wrong_token(self):
        assert _app().get("/", headers={"Authorization": "Bearer nope"}).status_code == 401

    def test_401_with_malformed_scheme(self):
        assert _app().get("/", headers={"Authorization": TOKEN}).status_code == 401

    def test_good_token_passes(self):
        response = _app().get("/", headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.status_code == 200
        assert response.text == "ok"
