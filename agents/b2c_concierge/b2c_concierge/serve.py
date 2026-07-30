"""serve.py — exposes b2c_concierge over A2A + the public /v3 facade (S09).

TWO identity regimes on ONE Starlette app, deliberately split:
- A2A surface (`/`, `/.well-known/agent-card.json`): the D7 interim bearer, same
  regime as the two leaves — peer AGENTS on the private network. FAIL-CLOSED:
  the process refuses to start without `A2A_BEARER_TOKEN`. The card is served
  UNSIGNED and open (discovery). D7 stays consolidated in b2c_common.auth so the
  oidc-mtls switch (before the S11 canary) happens in one place.
- Public facade (`/v3/*`, S09): the phase-minimum internal API key
  (`X-Internal-Api-Key`, facade.py) — its caller is the frontend/BFF replacing
  agent-usa, NOT a peer agent, so it must NOT be behind the D7 A2A bearer. The
  D7 gate is therefore applied to everything EXCEPT `/v3/*`; the facade routes
  carry their own auth. Keeping this composition here (not in b2c_common) leaves
  the D7 VERIFICATION logic single-sourced while the concierge owns which of its
  own paths are open.

A2A_HOST must be the host peers can reach (e.g. b2c-concierge.railway.internal): it is
written into the served card's url.
"""
import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from a2a.types import AgentCapabilities, HTTPAuthSecurityScheme, SecurityScheme
from b2c_common import BearerAuthMiddleware, require_bearer_token
from b2c_common.observability import A2aTurnObservation, flush_langfuse, setup_langfuse
from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from starlette.applications import Starlette

setup_langfuse("b2c-concierge")

from b2c_concierge.agent import root_agent  # noqa: E402
from b2c_concierge.facade import register_v3_routes  # noqa: E402

_HOST = os.environ.get("A2A_HOST", "localhost")
_PORT = int(os.environ.get("PORT", "8100"))

_BEARER_TOKEN = require_bearer_token()

# to_a2a auto-builds a card with no securitySchemes and capabilities.streaming unset; build it
# ourselves (S1 precedent) to advertise streaming AND the D7 interim bearer scheme. The two
# RemoteA2aAgent legs are NOT sub-agents of the spine, so build() stays offline (no card fetch).
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


@asynccontextmanager
async def _lifespan(app: Starlette) -> AsyncIterator[None]:
    yield
    flush_langfuse()  # flush only — the langfuse client owns its atexit shutdown


# The ADK A2A Starlette app. Mount the public /v3 facade routes on it BEFORE
# wrapping, so both surfaces share one app (one lifespan, one process).
# type-ignore: to_a2a annotates lifespan as `-> AsyncIterator` but consumes it as
# `async with lifespan(app)` — its own docstring example uses @asynccontextmanager.
_a2a_app = to_a2a(
    root_agent, host=_HOST, port=_PORT, agent_card=_agent_card,
    lifespan=_lifespan,  # type: ignore[arg-type]
)
register_v3_routes(_a2a_app)

# OBS4: the A2A surface gets a root observation of its own, so an A2A-driven
# turn (peer agent, eval battery, smoke) has a NAMED trace carrying the inbound
# request as input. Wrapped here rather than via add_middleware because it must
# NOT cover /v3/*: there `turn_observation` is already the root, and a second
# wrapper above it would steal the trace's name and input from `v3.chat`.
# Inside the D7 gate: an unauthenticated call must not open a trace.
_traced_a2a = A2aTurnObservation(_a2a_app, name=root_agent.name)

# D7 gate wraps the whole app; the dispatcher below sends /v3/* to the RAW app
# instead (facade owns its own internal-API-key auth), and everything else —
# A2A calls, the card, lifespan/websocket scopes — through the D7 gate.
_guarded = BearerAuthMiddleware(_traced_a2a, token=_BEARER_TOKEN)

_V3_PREFIX = "/v3"


async def app(scope, receive, send):
    """ASGI composition: /v3/* bypasses the D7 A2A bearer (public facade, own
    API-key gate); every other scope goes through the D7 gate."""
    if scope["type"] == "http" and scope.get("path", "").startswith(_V3_PREFIX):
        await _a2a_app(scope, receive, send)
        return
    await _guarded(scope, receive, send)
