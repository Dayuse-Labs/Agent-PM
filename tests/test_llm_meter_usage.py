"""Offline tests of the LLM meter's usage extraction (S-B).

The meter (scripts/run_llm_meter.py) logs ONLY usage facts — model, token
counts, latency — never request/response bodies or message content (GDPR).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_llm_meter.py"
_spec = importlib.util.spec_from_file_location("run_llm_meter", _SCRIPT)
assert _spec is not None and _spec.loader is not None
meter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(meter)


def test_usage_record_extracts_tokens_and_model():
    payload = {
        "model": "gpt-4o-mini-2024-07-18",
        "usage": {"prompt_tokens": 6500, "completion_tokens": 120, "total_tokens": 6620},
        "choices": [{"message": {"content": "SECRET USER CONTENT"}}],
    }
    record = meter.usage_record("/v1/chat/completions", payload, 432.15)
    assert record["model"] == "gpt-4o-mini-2024-07-18"
    assert record["prompt_tokens"] == 6500
    assert record["completion_tokens"] == 120
    assert record["total_tokens"] == 6620
    assert record["endpoint"] == "/v1/chat/completions"
    assert record["latency_ms"] == 432.2


def test_usage_record_never_carries_content():
    payload = {
        "model": "gpt-4o-mini",
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        "choices": [{"message": {"content": "PII-LADEN TEXT"}}],
    }
    record = meter.usage_record("/v1/chat/completions", payload, 1.0)
    serialized = str(record)
    assert "PII-LADEN" not in serialized
    assert "choices" not in record
    assert set(record) == {
        "ts", "endpoint", "model", "prompt_tokens", "completion_tokens",
        "total_tokens", "latency_ms",
    }


def test_usage_record_tolerates_missing_usage():
    record = meter.usage_record("/v1/embeddings", {"model": "text-embedding-3-small"}, 50.0)
    assert record["prompt_tokens"] is None
    assert record["completion_tokens"] is None
    assert record["model"] == "text-embedding-3-small"
