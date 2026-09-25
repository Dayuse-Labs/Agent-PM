"""AgentB2C shared foundations (interim D7 identity + market URL table + LLM params)."""
from .auth import AGENT_CARD_PATH, BearerAuthMiddleware, require_bearer_token
from .hotel_urls import build_hotel_page_url, with_checkin_date
from .pricing import display_price_euro
from .llm_params import max_tokens_for, reasoning_kwargs_for, role_model, temperature_kwargs_for
from .scores import GUARD_SCORE_NAMES, score_degraded, score_guards, score_ttft, score_turn

__all__ = [
    "AGENT_CARD_PATH",
    "BearerAuthMiddleware",
    "GUARD_SCORE_NAMES",
    "build_hotel_page_url",
    "display_price_euro",
    "max_tokens_for",
    "reasoning_kwargs_for",
    "require_bearer_token",
    "role_model",
    "score_degraded",
    "score_guards",
    "score_ttft",
    "score_turn",
    "temperature_kwargs_for",
    "with_checkin_date",
]
