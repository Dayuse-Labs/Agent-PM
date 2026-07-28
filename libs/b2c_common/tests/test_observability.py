"""observability.py (OBS1) — the Langfuse seam is opt-in and inert by default.

Locks the offline invariant: without LANGFUSE_PUBLIC_KEY/SECRET_KEY the module
must not import langfuse, install an OTel provider, or touch the network —
the whole test suite runs with it disabled, so these tests pin the OFF path
and the enrichment helpers' never-raise contract.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from b2c_common import observability


@pytest.fixture(autouse=True)
def _disabled(monkeypatch):
    """Default state for every test here: no keys, no cached client."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setattr(observability, "_client", None)


class TestSetupDisabledByDefault:
    def test_returns_none_without_keys(self):
        assert observability.setup_langfuse("test-service") is None
        assert observability.get_langfuse() is None

    def test_does_not_import_langfuse_without_keys(self):
        before = "langfuse" in sys.modules
        observability.setup_langfuse("test-service")
        # setup must not pull langfuse in as a side effect (offline suite);
        # tolerate another test having imported it deliberately.
        assert ("langfuse" in sys.modules) == before

    def test_one_key_alone_is_not_enough(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-x")
        assert observability.setup_langfuse("test-service") is None

    def test_idempotent_returns_cached_client(self, monkeypatch):
        sentinel = object()
        monkeypatch.setattr(observability, "_client", sentinel)
        assert observability.setup_langfuse("test-service") is sentinel

    def test_shutdown_is_a_noop_when_disabled(self):
        observability.shutdown_langfuse()  # must not raise


class TestTurnObservationDisabled:
    def test_yields_none_and_runs_the_block(self):
        ran = False
        with observability.turn_observation(
            name="v3.chat", session_id="s1", user_id="v3_s1", message="bonjour",
            is_synthetic=False, metadata={"turn_index": 0},
        ) as span:
            ran = True
            assert span is None
        assert ran


class TestStampLangfuseSession:
    def test_noop_when_disabled(self):
        # Junk context on the disabled path: no attribute access should matter.
        assert observability.stamp_langfuse_session(object()) is None

    def test_never_raises_on_junk_contexts_when_enabled(self, monkeypatch):
        monkeypatch.setattr(observability, "_client", object())
        for ctx in (
            object(),                                            # no run_config
            SimpleNamespace(run_config=None),                    # run_config None
            SimpleNamespace(run_config=SimpleNamespace(custom_metadata=None)),
            SimpleNamespace(run_config=SimpleNamespace(custom_metadata={})),
            SimpleNamespace(run_config=SimpleNamespace(
                custom_metadata={"a2a_metadata": {"dayuse_trace_id": 123}}  # non-str
            )),
        ):
            assert observability.stamp_langfuse_session(ctx) is None

    def test_stamps_session_attribute_from_a2a_metadata(self, monkeypatch):
        monkeypatch.setattr(observability, "_client", object())
        recorded: dict = {}

        span = SimpleNamespace(set_attribute=lambda k, v: recorded.__setitem__(k, v))
        import opentelemetry.trace

        monkeypatch.setattr(opentelemetry.trace, "get_current_span", lambda: span)
        ctx = SimpleNamespace(
            run_config=SimpleNamespace(
                custom_metadata={"a2a_metadata": {"dayuse_trace_id": "sess-42"}}
            )
        )
        assert observability.stamp_langfuse_session(ctx) is None
        assert recorded == {"langfuse.session.id": "sess-42"}
