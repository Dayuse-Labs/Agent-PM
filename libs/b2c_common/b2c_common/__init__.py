"""AgentB2C shared foundations (interim D7 identity + market URL table + LLM params)."""
from .auth import AGENT_CARD_PATH, BearerAuthMiddleware, require_bearer_token
from .hotel_urls import build_hotel_page_url, on_user_site, site_host, with_checkin_date
from .pricing import (
    display_price_euro,
    display_price_hotel,
    format_minor_amount,
    hotel_currency_price,
    minor_units,
)
from .llm_params import (
    DEFAULT_MODEL,
    max_tokens_for,
    max_tokens_kwargs_for,
    reasoning_kwargs_for,
    role_model,
    temperature_kwargs_for,
)
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
    "DEFAULT_MODEL",
    "FALLBACK_SCORE_NAMES",
    "GUARD_SCORE_NAMES",
    "build_hotel_page_url",
    "display_price_euro",
    "display_price_hotel",
    "format_minor_amount",
    "hotel_currency_price",
    "max_tokens_for",
    "max_tokens_kwargs_for",
    "minor_units",
    "on_user_site",
    "reasoning_kwargs_for",
    "require_bearer_token",
    "role_model",
    "score_degraded",
    "score_fallbacks",
    "score_guards",
    "score_ttft",
    "score_turn",
    "site_host",
    "temperature_kwargs_for",
    "with_checkin_date",
]
