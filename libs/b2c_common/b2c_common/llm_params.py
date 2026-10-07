"""Per-role LLM parameters — model slug, reasoning cap, max_tokens.

Why this exists (latency audit 2026-07-28): the deployed stack was switched to
a reasoning model (`DAYUSE_MODEL=gpt-5.2`) with NO cap anywhere — a measured
×2 turn-latency regression (HANDOFF 2026-07-23). Three gaps this module closes:

1. **One slug ruled every role.** Triage is a closed-enum extraction and the
   leaves emit tool calls — an economy model is enough there regardless of
   what the synthesis runs. `role_model()` adds per-role env overrides
   (`DAYUSE_MODEL_TRIAGE`, `DAYUSE_MODEL_SYNTHESIS`, …) falling back to
   `DAYUSE_MODEL`, so the mix is an env change, not a deploy.
2. **The fleet's reasoning cap is OpenRouter-shaped.** `dayuse_agent_common.
   reasoning_kwargs()` emits `extra_body={"reasoning": …}` — correct for
   `openrouter/*` slugs, but on OpenAI-direct slugs (gpt-5*, o-series) that
   body key is not a valid request param. `reasoning_kwargs_for()` translates
   `DAYUSE_REASONING_EFFORT` per provider and NEVER emits a param the target
   family does not support (unknown families get `{}`, not a guess).
3. **No completion was bounded.** `max_tokens_for()` gives triage/synthesis
   sane ceilings — on a reasoning model, unbounded thinking tokens are
   unbounded latency. Triage truncation degrades to the regex fallback by
   design (triage.py: any failure → fallback, never a hard fail).

Everything reads the environment AT CALL TIME (the `_leaf_timeout` pattern:
monkeypatch-friendly, no restart needed for a router-level change) and is a
strict NO-OP when the env vars are unset — requests stay bit-identical to the
pre-audit behaviour, locked by tests.
"""
from __future__ import annotations

import os

from dayuse_agent_common import reasoning_kwargs as _openrouter_reasoning_kwargs

_DEFAULT_MODEL = "gpt-4o-mini"

# The fleet's "disable" spellings all map to "none" — live-probed on gpt-5.2
# (2026-07-28): its accepted set is {none, low, medium, high, xhigh}; "minimal"
# (the older gpt-5.0 floor) is a 400. Other effort values pass through
# verbatim, so an operator mismatch fails LOUDLY at the provider rather than
# being silently rewritten here.
_DISABLE_SPELLINGS = {"none", "off", "false", "0", "disabled", "disable"}

# Model families that take LiteLLM's unified `reasoning_effort` param on the
# OpenAI-direct path. Prefix match on the bare slug (no provider prefix).
_OPENAI_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")

_MAX_TOKENS_DEFAULTS = {
    # Triage answers ~40 tokens of JSON; headroom covers reasoning tokens
    # (they count against max_tokens on OpenAI reasoning models).
    "TRIAGE": 200,
    # Synthesis replies are ~150-300 tokens; same reasoning-token headroom.
    # 1000 was all spent on reasoning once (QA trace 62207822, gpt-5.2:
    # finish_reason=length, empty content) — 2000 per ticket mcp-dayuse#8.
    "SYNTHESIS": 2000,
}


def role_model(role: str) -> str:
    """The model slug for a role: `DAYUSE_MODEL_{ROLE}` > `DAYUSE_MODEL` > default."""
    return (
        os.environ.get(f"DAYUSE_MODEL_{role.upper()}", "").strip()
        or os.environ.get("DAYUSE_MODEL", "").strip()
        or _DEFAULT_MODEL
    )


def reasoning_kwargs_for(model_slug: str) -> dict:
    """Provider-aware translation of DAYUSE_REASONING_EFFORT for one model slug.

    - unset/empty         → {} (bit-identical requests — the safe default)
    - `openrouter/…`      → the fleet's validated OpenRouter shape (delegated)
    - OpenAI reasoning families (gpt-5*, o1/o3/o4*) → {"reasoning_effort": …},
      with the disable spellings mapped to "none" (probed on gpt-5.2)
    - anything else (gpt-4o-mini, …) → {} — never send an unsupported param
    """
    effort = (os.environ.get("DAYUSE_REASONING_EFFORT") or "").strip().lower()
    if not effort:
        return {}
    if model_slug.startswith("openrouter/"):
        return _openrouter_reasoning_kwargs()
    bare = model_slug.rsplit("/", 1)[-1]
    if bare.startswith(_OPENAI_REASONING_PREFIXES):
        return {"reasoning_effort": "none" if effort in _DISABLE_SPELLINGS else effort}
    return {}


def temperature_kwargs_for(model_slug: str, temperature: float) -> dict:
    """`{"temperature": …}` — unless the reasoning cap makes it illegal.

    Live-caught on the Railway demo (2026-07-28): sending `temperature` and a
    non-"none" `reasoning_effort` TOGETHER to a gpt-5* slug raises litellm's
    client-side UnsupportedParamsError ("Only temperature=1 is supported…
    temperature is supported when reasoning_effort='none'") — every synthesis
    silently fell back to leaf-text-verbatim. Probed: each param alone is
    fine, and temperature + effort="none" is fine. So temperature is dropped
    ONLY in the one combination that rejects it; the reasoning cap wins (it is
    the latency lever; temperature is a nice-to-have)."""
    effort = reasoning_kwargs_for(model_slug).get("reasoning_effort")
    if effort is not None and effort != "none":
        return {}
    return {"temperature": temperature}


def max_tokens_for(role: str) -> int | None:
    """Completion ceiling for a role, or None (uncapped).

    `DAYUSE_MAX_TOKENS_{ROLE}` overrides the built-in default; `0` disables
    the cap explicitly; a role without a default stays uncapped.
    """
    raw = os.environ.get(f"DAYUSE_MAX_TOKENS_{role.upper()}", "").strip()
    if raw:
        value = int(raw)
        return value if value > 0 else None
    default = _MAX_TOKENS_DEFAULTS.get(role.upper())
    return default
