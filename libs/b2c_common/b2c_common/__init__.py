"""AgentB2C shared foundations (interim D7 identity + market URL table + LLM params)."""
from .auth import AGENT_CARD_PATH, BearerAuthMiddleware, require_bearer_token
from .hotel_urls import build_hotel_page_url, with_checkin_date
from .pricing import (
    display_price_euro,
    display_price_hotel,
    format_minor_amount,
    hotel_currency_price,
    minor_units,
)
from .llm_params import max_tokens_for, reasoning_kwargs_for, role_model, temperature_kwargs_for
from .scores import (
    FALLBACK_SCORE_NAMES,
    GUARD_SCORE_NAMES,
    score_degraded,
    score_fallbacks,
    score_guards,
    score_ttft,
    score_turn,
)

__all__ = [
    "AGENT_CARD_PATH",
    "BearerAuthMiddleware",
    "FALLBACK_SCORE_NAMES",
    "GUARD_SCORE_NAMES",
    "build_hotel_page_url",
    "display_price_euro",
    "display_price_hotel",
    "format_minor_amount",
    "hotel_currency_price",
    "max_tokens_for",
    "minor_units",
    "reasoning_kwargs_for",
    "require_bearer_token",
    "role_model",
    "score_degraded",
    "score_fallbacks",
    "score_guards",
    "score_ttft",
    "score_turn",
    "temperature_kwargs_for",
    "with_checkin_date",
]
