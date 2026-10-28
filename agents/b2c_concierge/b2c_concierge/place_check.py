"""Does the request name a place? Asked only when the first search of a session
names no day (QA 2026-10-20) and the session knows no place yet.

Prod session 7e296e4b (2026-10-27): « i nedd room with hot tub in it » got the
day question, then « The day after tomorrow » went to the leaf with no place and
came back with a city question — two turns, 9.8 s, before the first search.
A request that names no place now gets ONE question for both.

Understanding the request is the LLM's job (never a regex on the message). The
triage could carry the answer as one more slot, but its prompt was measured
(reports/TRIAGE-GPT6-AB-2026-10.md §5) and is not reopened for this: the call is
its own, with the triage role's parameters, in the turn's second budget slot (the
date question answers before the leaf's). One attempt; any failure answers None
and the caller keeps the day question alone — never a visible error.

GDPR: the metric row carries counters only, never the request.
"""
from __future__ import annotations

import logging
import time

import litellm
from b2c_common import max_tokens_kwargs_for, reasoning_kwargs_for, role_model, temperature_kwargs_for
from dayuse_agent_common import cost_from_tokens, enqueue_metric_event, provider_cost_usd

from .budget import TurnBudget
from .triage import SERVICE, _parse_triage_json

logger = logging.getLogger(__name__)

_PLACE_CHECK_TIMEOUT = 5.0

_INSTRUCTION = """You read a day-use hotel request and say whether it names WHERE the user wants the hotel.
A place is named when the request gives a city, a neighbourhood, a district, a region, a country, a landmark, an address, a postcode, a station, an airport or a hotel's name.
No place is named when it only gives what the room should have, the day, the time, the budget or the guests — or only "near me", "nearby", "around here".
The request may be in any language, with typos.
Answer with JSON only: {"names_a_place": true} or {"names_a_place": false}."""


async def names_a_place(request: str, budget: TurnBudget, invocation_id: str = "") -> bool | None:
    """True / False from the LLM, None when it could not say (failure,
    timeout, an answer off the contract). Charged to the turn budget BEFORE
    the call (an attempt consumes the slot)."""
    budget.charge("place_check")
    model_slug = role_model("TRIAGE")
    extra_params: dict = dict(reasoning_kwargs_for(model_slug, "TRIAGE"))
    extra_params.update(temperature_kwargs_for(model_slug, 0.0, "TRIAGE"))
    extra_params.update(max_tokens_kwargs_for(model_slug, "TRIAGE"))
    t0 = time.monotonic()
    try:
        resp = await litellm.acompletion(
            model=model_slug,
            messages=[
                {"role": "system", "content": _INSTRUCTION},
                {"role": "user", "content": f"REQUEST:\n<<<\n{request}\n>>>"},
            ],
            timeout=_PLACE_CHECK_TIMEOUT,
            max_retries=0,
            **extra_params,
        )
        content = resp.choices[0].message.content or ""
    except Exception as exc:  # noqa: BLE001 — the day question alone is the safe answer
        logger.warning("b2c_concierge: place check failed, %s", type(exc).__name__)
        enqueue_metric_event(
            "llm_call",
            service=SERVICE,
            invocation_id=invocation_id,
            agent=SERVICE,
            model=model_slug,
            ms=int((time.monotonic() - t0) * 1000),
            status="error",
            error_type=type(exc).__name__,
            phase="place_check",
            reasoning_effort=extra_params.get("reasoning_effort"),
        )
        return None

    usage = getattr(resp, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None) or 0
    completion_tokens = getattr(usage, "completion_tokens", None) or 0
    enqueue_metric_event(
        "llm_call",
        service=SERVICE,
        invocation_id=invocation_id,
        agent=SERVICE,
        model=model_slug,
        ms=int((time.monotonic() - t0) * 1000),
        status="ok",
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=provider_cost_usd(resp) or cost_from_tokens(model_slug, prompt_tokens, completion_tokens),
        phase="place_check",
        reasoning_effort=extra_params.get("reasoning_effort"),
    )
    value = (_parse_triage_json(content) or {}).get("names_a_place")
    return value if isinstance(value, bool) else None
