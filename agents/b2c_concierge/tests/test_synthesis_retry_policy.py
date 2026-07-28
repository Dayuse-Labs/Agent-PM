"""Synthesis retry policy (S-G4): plain `acompletion(num_retries=N)` retries
BLINDLY regardless of exception type (verified live against a stub endpoint:
a 400/401 was retried exactly as many times as a 429) — `litellm.Router` +
`RetryPolicy` is the only litellm construct that retries PER EXCEPTION TYPE,
also verified live (400/401 -> 1 request, 429 -> 1 + num_retries requests).

These tests assert OUR wiring (the Router is configured correctly, cached per
model slug, and reachable from `_generate_once`) — not litellm's own retry
mechanics, which are third-party behavior already verified against a live
stub server (not re-tested here to keep this suite network-free)."""
from __future__ import annotations

import litellm

import b2c_concierge.agent as agent_module
from b2c_concierge.agent import (
    _SYNTHESIS_MODEL_GROUP,
    _SYNTHESIS_NUM_RETRIES,
    _get_synthesis_router,
    _reset_synthesis_routers,
)


class TestRetryPolicyConfig:
    def setup_method(self):
        _reset_synthesis_routers()

    def teardown_method(self):
        _reset_synthesis_routers()

    def test_transient_errors_get_the_configured_retry_count(self):
        router = _get_synthesis_router("gpt-4o-mini")
        policy = router.retry_policy
        assert policy.TimeoutErrorRetries == _SYNTHESIS_NUM_RETRIES
        assert policy.RateLimitErrorRetries == _SYNTHESIS_NUM_RETRIES

    def test_permanent_errors_get_zero_retries(self):
        router = _get_synthesis_router("gpt-4o-mini")
        policy = router.retry_policy
        assert policy.BadRequestErrorRetries == 0
        assert policy.AuthenticationErrorRetries == 0
        assert policy.ContentPolicyViolationErrorRetries == 0

    def test_no_blind_retry_outside_the_policy(self):
        # num_retries=0 at the Router level: the RetryPolicy above must be the
        # ONLY retry source, never stacked with a second blind retry layer.
        router = _get_synthesis_router("gpt-4o-mini")
        assert router.num_retries == 0

    def test_model_list_maps_the_fixed_alias_to_the_real_model_slug(self):
        router = _get_synthesis_router("openai/gpt-4o")
        deployments = router.get_model_list(model_name=_SYNTHESIS_MODEL_GROUP)
        assert deployments and deployments[0]["litellm_params"]["model"] == "openai/gpt-4o"


class TestRouterCaching:
    def setup_method(self):
        _reset_synthesis_routers()

    def teardown_method(self):
        _reset_synthesis_routers()

    def test_same_model_slug_reuses_the_cached_router(self):
        first = _get_synthesis_router("gpt-4o-mini")
        second = _get_synthesis_router("gpt-4o-mini")
        assert first is second

    def test_different_model_slug_gets_its_own_router(self):
        first = _get_synthesis_router("gpt-4o-mini")
        second = _get_synthesis_router("gpt-4o")
        assert first is not second

    def test_reset_hook_drops_the_cache(self):
        before = _get_synthesis_router("gpt-4o-mini")
        _reset_synthesis_routers()
        after = _get_synthesis_router("gpt-4o-mini")
        assert before is not after


class TestGenerateOnceUsesTheRouter:
    def setup_method(self):
        _reset_synthesis_routers()

    def teardown_method(self):
        _reset_synthesis_routers()

    def test_generate_once_routes_through_the_synthesis_router(self, monkeypatch):
        # Router.acompletion calls litellm.acompletion internally (by attribute
        # lookup, verified live) — patching the module-level function still
        # intercepts a call made THROUGH the Router, same as every existing
        # test_spine_profile.py / test_spine.py ScriptedLlm mock relies on.
        calls: list[dict] = []

        async def fake_acompletion(**kwargs):
            calls.append(kwargs)
            return litellm.ModelResponse(
                choices=[
                    {"message": {"role": "assistant", "content": "hi"}, "index": 0, "finish_reason": "stop"}
                ]
            )

        monkeypatch.setattr(agent_module.litellm, "acompletion", fake_acompletion)
        agent = agent_module.root_agent

        import asyncio

        result = asyncio.run(
            agent._generate_once(
                message="bonjour",
                language="fr",
                leaf_text="2 offers found",
                ground_truth_block="",
                widen_note=None,
                invocation_id="test-inv",
            )
        )
        assert result == "hi"
        assert len(calls) == 1
        assert calls[0]["model"] == "gpt-4o-mini"  # the real slug, not the Router alias
        # Latency audit 2026-07-28 — bounded synthesis is the one deliberate
        # default change; the reasoning cap stays absent while env is unset.
        assert calls[0]["max_tokens"] == 1000
        assert "reasoning_effort" not in calls[0]

    def test_per_role_model_and_reasoning_cap(self, monkeypatch):
        """DAYUSE_MODEL_SYNTHESIS wins over DAYUSE_MODEL, and the reasoning cap
        reaches the call for a reasoning slug (provider-aware, llm_params)."""
        calls: list[dict] = []

        async def fake_acompletion(**kwargs):
            calls.append(kwargs)
            return litellm.ModelResponse(
                choices=[
                    {"message": {"role": "assistant", "content": "hi"}, "index": 0, "finish_reason": "stop"}
                ]
            )

        monkeypatch.setattr(agent_module.litellm, "acompletion", fake_acompletion)
        monkeypatch.setenv("DAYUSE_MODEL", "gpt-4o-mini")
        monkeypatch.setenv("DAYUSE_MODEL_SYNTHESIS", "gpt-5.2")
        monkeypatch.setenv("DAYUSE_REASONING_EFFORT", "low")

        import asyncio

        result = asyncio.run(
            agent_module.root_agent._generate_once(
                message="bonjour",
                language="fr",
                leaf_text="2 offers found",
                ground_truth_block="",
                widen_note=None,
                invocation_id="test-inv",
            )
        )
        assert result == "hi"
        assert calls[0]["model"] == "gpt-5.2"
        assert calls[0]["reasoning_effort"] == "low"
