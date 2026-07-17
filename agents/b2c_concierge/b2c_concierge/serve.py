"""serve.py — exposes b2c_concierge over A2A (Agent Card at /.well-known/agent-card.json).

The public iso-contract facade (POST /v3/chat + SSE) lands in S9; until then the
orchestrator is only reachable over A2A on the private network, under the same
interim identity regime as the leaves.

A2A_HOST must be the host peers can reach (e.g. b2c-concierge.railway.internal): it is
written into the served card's url.

Interim identity (D7), same regime as the two leaves — consolidated in b2c_common.auth
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

from b2c_concierge.agent import root_agent

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


app = to_a2a(root_agent, host=_HOST, port=_PORT, agent_card=_agent_card)
app.add_middleware(BearerAuthMiddleware, token=_BEARER_TOKEN)
