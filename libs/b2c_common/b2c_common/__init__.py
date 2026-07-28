"""AgentB2C shared foundations (interim D7 identity + market URL table + LLM params)."""
from .auth import AGENT_CARD_PATH, BearerAuthMiddleware, require_bearer_token
from .hotel_urls import build_hotel_page_url
from .llm_params import max_tokens_for, reasoning_kwargs_for, role_model

__all__ = [
    "AGENT_CARD_PATH",
    "BearerAuthMiddleware",
    "build_hotel_page_url",
    "max_tokens_for",
    "reasoning_kwargs_for",
    "require_bearer_token",
    "role_model",
]
