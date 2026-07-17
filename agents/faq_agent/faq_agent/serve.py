"""serve.py — exposes faq_agent over A2A (Agent Card at /.well-known/agent-card.json).

A2A_HOST must be the host peers can reach (e.g. faq-agent.railway.internal): it is written
into the served card's url, and RemoteA2aAgent callers POST to that url — with the default
localhost a remote caller would call ITSELF.

Interim identity (D7), same regime as hotel_search_agent:
- every route requires `Authorization: Bearer $A2A_BEARER_TOKEN`, EXCEPT the agent card
  (discovery must stay open);
- FAIL-CLOSED: the process refuses to start without a token — "dev-insecure" is never deployed;
- the card is served UNSIGNED (sign_agent_card is not implemented in dayuse_agent_common yet):
  documented D7 exception, deadline = oidc-mtls switch, at the latest before the S11 canary.
"""
import asyncio
import hmac
import os

from a2a.types import AgentCapabilities, HTTPAuthSecurityScheme, SecurityScheme
from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from starlette.responses import JSONResponse

from faq_agent.agent import root_agent

AGENT_CARD_PATH = "/.well-known/agent-card.json"

_HOST = os.environ.get("A2A_HOST", "localhost")
_PORT = int(os.environ.get("PORT", "8102"))

_BEARER_TOKEN = os.environ.get("A2A_BEARER_TOKEN", "").strip()
if not _BEARER_TOKEN:
    raise RuntimeError(
        "A2A_BEARER_TOKEN is missing/empty: this leaf fails closed (D7 — dev-insecure is never "
        "deployed). Set it in the environment (any non-empty static token for local dev)."
    )

# to_a2a auto-builds a card with no securitySchemes and capabilities.streaming unset; build it
# ourselves (S1 precedent) to advertise streaming AND the D7 interim bearer scheme so callers
# discover how to authenticate. build() is async + offline (no remote sub-agents), run once.
_agent_card = asyncio.run(
    AgentCardBuilder(
        agent=root_agent,
        rpc_url=f"http://{_HOST}:{_PORT}/",
        capabilities=AgentCapabilities(streaming=True),
    ).build()
)
_agent_card.security_schemes = {
    "bearer-interim": SecurityScheme(
        root=HTTPAuthSecurityScheme(
            type="http",
            scheme="bearer",
            description=(
                "Interim static bearer over the private network (D7 exception, unsigned card); "
                "replaced by oidc-mtls at the latest before the S11 canary."
            ),
        )
    )
}
_agent_card.security = [{"bearer-interim": []}]


class BearerAuthMiddleware:
    """Pure-ASGI D7 gate: constant-time bearer check on every route except the card."""

    def __init__(self, app, token: str) -> None:
        self._app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == AGENT_CARD_PATH:
            await self._app(scope, receive, send)
            return
        authorization = next(
            (value for key, value in scope["headers"] if key == b"authorization"), b""
        )
        if not hmac.compare_digest(authorization, self._expected):
            response = JSONResponse(
                {"detail": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)


app = to_a2a(root_agent, host=_HOST, port=_PORT, agent_card=_agent_card)
app.add_middleware(BearerAuthMiddleware, token=_BEARER_TOKEN)
