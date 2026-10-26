"""serve.py — exposes faq_agent over A2A (Agent Card at /.well-known/agent-card.json).

A2A_HOST must be the host peers can reach (e.g. faq-agent.railway.internal): it is written
into the served card's url, and RemoteA2aAgent callers POST to that url — with the default
localhost a remote caller would call ITSELF.

Interim identity (D7), same regime as hotel_search_agent — consolidated in b2c_common.auth
(S3) so the oidc-mtls switch happens in one place:
- every route requires `Authorization: Bearer $A2A_BEARER_TOKEN`, EXCEPT the agent card
  (discovery must stay open);
- FAIL-CLOSED: the process refuses to start without a token;
- the card is served UNSIGNED (sign_agent_card is not implemented in dayuse_agent_common yet):
  documented D7 exception, deadline = oidc-mtls switch, at the latest before the S11 canary.
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

# Before the agent import (uniform with the concierge; also future-proofs the
# litellm patch order if instrument_litellm ever flips). instrument_litellm=False:
# ADK's own `generate_content` span already carries model/usage/content in the
# leaves — a second generation span per call would double-count tokens and cost.
setup_langfuse("faq-agent", instrument_litellm=False)

from faq_agent.agent import root_agent  # noqa: E402

_HOST = os.environ.get("A2A_HOST", "localhost")
_PORT = int(os.environ.get("PORT", "8102"))

_BEARER_TOKEN = require_bearer_token()

# to_a2a auto-builds a card with no securitySchemes and capabilities.streaming unset; build it
# ourselves (S1 precedent) to advertise streaming AND the D7 interim bearer scheme so callers
# discover how to authenticate. build() lists the agent's tools, so it opens one MCP_B2C session
# at import (tests stub McpToolset.get_tools); run once.
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


# type-ignore: to_a2a annotates lifespan as `-> AsyncIterator` but consumes it as
# `async with lifespan(app)` — its own docstring example uses @asynccontextmanager.
app = to_a2a(
    root_agent, host=_HOST, port=_PORT, agent_card=_agent_card,
    lifespan=_lifespan,  # type: ignore[arg-type]
)
# OBS4: joins the caller's trace (W3C headers) and opens the leaf's root
# observation. Added BEFORE the D7 gate on purpose — add_middleware puts the
# LAST added outermost, so the bearer check rejects an unauthenticated call
# before any trace is opened for it. No-op without LANGFUSE_* keys.
app.add_middleware(A2aTurnObservation, name=root_agent.name)
app.add_middleware(BearerAuthMiddleware, token=_BEARER_TOKEN)
