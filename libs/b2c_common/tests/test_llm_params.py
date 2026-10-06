"""Per-role LLM params (latency audit 2026-07-28) — the three locks that
matter: (1) everything is a strict NO-OP when the env vars are unset (requests
stay bit-identical to the pre-audit behaviour), (2) the reasoning cap is
provider-aware and NEVER emits a param the target family does not support
(the fleet's OpenRouter shape would 400 on OpenAI-direct slugs), (3) the
role precedence is DAYUSE_MODEL_{ROLE} > DAYUSE_MODEL > gpt-4o-mini."""
from __future__ import annotations

import pytest

from b2c_common import max_tokens_for, reasoning_kwargs_for, role_model, temperature_kwargs_for


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "DAYUSE_MODEL",
        "DAYUSE_MODEL_TRIAGE",
        "DAYUSE_MODEL_SYNTHESIS",
        "DAYUSE_REASONING_EFFORT",
        "DAYUSE_MAX_TOKENS_TRIAGE",
        "DAYUSE_MAX_TOKENS_SYNTHESIS",
    ):
        monkeypatch.delenv(var, raising=False)


class TestRoleModelPrecedence:
    def test_defaults_to_gpt_4o_mini_with_nothing_set(self):
        assert role_model("TRIAGE") == "gpt-4o-mini"

    def test_dayuse_model_wins_over_the_default(self, monkeypatch):
        monkeypatch.setenv("DAYUSE_MODEL", "gpt-5.2")
        assert role_model("TRIAGE") == "gpt-5.2"
        assert role_model("SYNTHESIS") == "gpt-5.2"

    def test_role_override_wins_over_dayuse_model(self, monkeypatch):
        monkeypatch.setenv("DAYUSE_MODEL", "gpt-5.2")
        monkeypatch.setenv("DAYUSE_MODEL_TRIAGE", "gpt-4o-mini")
        assert role_model("TRIAGE") == "gpt-4o-mini"
        # The other role keeps the shared slug — the mix is per role.
        assert role_model("SYNTHESIS") == "gpt-5.2"

    def test_blank_override_falls_through(self, monkeypatch):
        monkeypatch.setenv("DAYUSE_MODEL", "gpt-5.2")
        monkeypatch.setenv("DAYUSE_MODEL_TRIAGE", "   ")
        assert role_model("TRIAGE") == "gpt-5.2"

    def test_role_is_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("DAYUSE_MODEL_TRIAGE", "gpt-4o-mini")
        assert role_model("triage") == "gpt-4o-mini"


class TestReasoningKwargsProviderAware:
    def test_unset_effort_is_a_strict_noop_for_every_slug(self):
        for slug in ("gpt-4o-mini", "gpt-5.2", "o3-mini", "openrouter/z-ai/glm-5.2"):
            assert reasoning_kwargs_for(slug) == {}

    def test_openai_reasoning_families_get_the_unified_param(self, monkeypatch):
        monkeypatch.setenv("DAYUSE_REASONING_EFFORT", "low")
        assert reasoning_kwargs_for("gpt-5.2") == {"reasoning_effort": "low"}
        assert reasoning_kwargs_for("o3-mini") == {"reasoning_effort": "low"}
        # Provider-prefixed slugs match on the bare model name.
        assert reasoning_kwargs_for("azure/gpt-5.2") == {"reasoning_effort": "low"}

    def test_disable_spellings_map_to_none_on_openai(self, monkeypatch):
        # Live-probed on gpt-5.2 (2026-07-28): accepted set is
        # {none, low, medium, high, xhigh} — "minimal" is a 400.
        for spelling in ("none", "off", "false", "0", "disabled"):
            monkeypatch.setenv("DAYUSE_REASONING_EFFORT", spelling)
            assert reasoning_kwargs_for("gpt-5.2") == {"reasoning_effort": "none"}

    def test_other_efforts_pass_through_verbatim(self, monkeypatch):
        # An operator mismatch (e.g. "minimal" on gpt-5.2) must fail LOUDLY at
        # the provider, never be silently rewritten here.
        monkeypatch.setenv("DAYUSE_REASONING_EFFORT", "xhigh")
        assert reasoning_kwargs_for("gpt-5.2") == {"reasoning_effort": "xhigh"}

    def test_openrouter_slugs_delegate_to_the_fleet_shape(self, monkeypatch):
        monkeypatch.setenv("DAYUSE_REASONING_EFFORT", "low")
        assert reasoning_kwargs_for("openrouter/z-ai/glm-5.2") == {
            "extra_body": {"reasoning": {"effort": "low"}}
        }

    def test_non_reasoning_models_never_get_the_param(self, monkeypatch):
        # gpt-4o-mini would 400 on reasoning_effort — the cap must not leak.
        monkeypatch.setenv("DAYUSE_REASONING_EFFORT", "low")
        assert reasoning_kwargs_for("gpt-4o-mini") == {}
        assert reasoning_kwargs_for("mistral/mistral-small") == {}


class TestTemperatureYieldsToTheReasoningCap:
    """Live-caught on the Railway demo (2026-07-28): temperature + a non-none
    reasoning_effort together on gpt-5* raise litellm's UnsupportedParamsError
    — every synthesis silently fell back to leaf-text-verbatim. Probed: each
    param alone is fine; temperature + effort='none' is fine."""

    def test_temperature_kept_when_no_reasoning_cap(self):
        assert temperature_kwargs_for("gpt-5.2", 0.2) == {"temperature": 0.2}
        assert temperature_kwargs_for("gpt-4o-mini", 0.0) == {"temperature": 0.0}

    def test_temperature_dropped_on_the_illegal_combination(self, monkeypatch):
        monkeypatch.setenv("DAYUSE_REASONING_EFFORT", "low")
        assert temperature_kwargs_for("gpt-5.2", 0.2) == {}

    def test_temperature_kept_with_effort_none(self, monkeypatch):
        # Probed on gpt-5.2: temperature IS supported when effort='none'.
        monkeypatch.setenv("DAYUSE_REASONING_EFFORT", "off")
        assert temperature_kwargs_for("gpt-5.2", 0.2) == {"temperature": 0.2}

    def test_non_reasoning_models_keep_temperature_even_with_effort_set(self, monkeypatch):
        # gpt-4o-mini gets no reasoning param at all → no collision to avoid.
        monkeypatch.setenv("DAYUSE_REASONING_EFFORT", "low")
        assert temperature_kwargs_for("gpt-4o-mini", 0.0) == {"temperature": 0.0}

    def test_openrouter_slugs_keep_temperature(self, monkeypatch):
        # The OpenRouter reasoning shape (extra_body) coexists with temperature.
        monkeypatch.setenv("DAYUSE_REASONING_EFFORT", "low")
        assert temperature_kwargs_for("openrouter/z-ai/glm-5.2", 0.2) == {"temperature": 0.2}


class TestMaxTokens:
    def test_built_in_defaults(self):
        assert max_tokens_for("TRIAGE") == 650
        assert max_tokens_for("SYNTHESIS") == 1000

    def test_unknown_role_is_uncapped(self):
        assert max_tokens_for("LEAF") is None

    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("DAYUSE_MAX_TOKENS_TRIAGE", "500")
        assert max_tokens_for("TRIAGE") == 500

    def test_zero_disables_the_cap(self, monkeypatch):
        monkeypatch.setenv("DAYUSE_MAX_TOKENS_SYNTHESIS", "0")
        assert max_tokens_for("SYNTHESIS") is None
