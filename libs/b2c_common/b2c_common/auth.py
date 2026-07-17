"""b2c_common.auth — interim D7 identity, ONE implementation for the 3 AgentB2C services.

Consolidation S3: the same fail-closed static-bearer gate was copy-pasted in the three
serve.py files; it now lives here so the oidc-mtls switch (at the latest before the S11
canary) happens in exactly one place.

Why not dayuse_agent_common: the fleet lib has NO inbound bearer verification (booking_qa
accepts any caller) and its oidc-mtls provider is a NotImplementedError stub — AgentB2C's
interim regime (D7) is deliberately STRICTER than the fleet. The lib's `dev-insecure`
identity provider is local-only and must never appear in a deployment config (locked by
libs/b2c_common/tests/test_no_dev_insecure.py).
"""
from __future__ import annotations

import hmac
import os

from starlette.responses import JSONResponse

AGENT_CARD_PATH = "/.well-known/agent-card.json"


def require_bearer_token(env_var: str = "A2A_BEARER_TOKEN") -> str:
    """Fail-closed read of the inbound D7 bearer: empty/missing kills the boot.

    'dev-insecure' is never deployed; local dev uses any non-empty static token
    (scripts/run_local.sh defaults one).
    """
    token = os.environ.get(env_var, "").strip()
    if not token:
        raise RuntimeError(
            f"{env_var} is missing/empty: this service fails closed (D7 — dev-insecure is "
            "never deployed). Set it in the environment (any non-empty static token for "
            "local dev)."
        )
    return token


class BearerAuthMiddleware:
    """Pure-ASGI D7 gate: constant-time bearer check on every route except the agent card
    (discovery must stay open)."""

    def __init__(self, app, token: str, card_path: str = AGENT_CARD_PATH) -> None:
        self._app = app
        self._expected = f"Bearer {token}".encode()
        self._card_path = card_path

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == self._card_path:
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
