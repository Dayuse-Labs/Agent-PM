"""AgentB2C shared foundations (interim D7 identity + market URL table)."""
from .auth import AGENT_CARD_PATH, BearerAuthMiddleware, require_bearer_token
from .hotel_urls import build_hotel_page_url

__all__ = [
    "AGENT_CARD_PATH",
    "BearerAuthMiddleware",
    "build_hotel_page_url",
    "require_bearer_token",
]
