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

from a2a.types import AgentCapabilities, HTTPAuthSecurityScheme, SecurityScheme
from b2c_common import BearerAuthMiddleware, require_bearer_token
from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder
from google.adk.a2a.utils.agent_to_a2a import to_a2a

from faq_agent.agent import root_agent

_HOST = os.environ.get("A2A_HOST", "localhost")
_PORT = int(os.environ.get("PORT", "8102"))

_BEARER_TOKEN = require_bearer_token()

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


app = to_a2a(root_agent, host=_HOST, port=_PORT, agent_card=_agent_card)
app.add_middleware(BearerAuthMiddleware, token=_BEARER_TOKEN)
