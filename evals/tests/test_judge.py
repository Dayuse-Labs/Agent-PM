"""Offline tests for the LLM-as-judge (litellm mocked — no network, no key)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from evals import judge as judge_module
from evals.judge import LLMJudge, _extract_json


def _resp(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def test_extract_json_plain():
    assert _extract_json('{"verdict": "pass", "score": 5}')["verdict"] == "pass"


def test_extract_json_fenced():
    raw = 'here you go:\n```json\n{"verdict": "fail", "score": 2}\n```\ndone'
    assert _extract_json(raw)["score"] == 2


def test_extract_json_embedded_braces():
    assert _extract_json('noise {"verdict":"pass","score":4} trailing')["score"] == 4


def test_extract_json_unparseable_raises():
    with pytest.raises(Exception):
        _extract_json("no json here at all")


def test_parse_maps_fields_and_clamps():
    j = LLMJudge(model="x")._parse(
        "sc1", "compare", '{"verdict":"pass","score":9,"reasoning":"ok","red_flags":[]}'
    )
    assert j.verdict == "pass" and j.passed
    assert j.score == 5.0  # clamped to [1,5]
    assert j.reasoning == "ok"


def test_parse_unknown_verdict_defaults_fail():
    j = LLMJudge(model="x")._parse("sc", "faq", '{"verdict":"maybe","score":3}')
    assert j.verdict == "fail"


def test_parse_garbage_is_error_verdict():
    j = LLMJudge(model="x")._parse("sc", "faq", "totally not json")
    assert j.verdict == "error" and j.score == 0.0


def test_evaluate_empty_answers_fails_without_calling_llm(monkeypatch):
    called = False

    async def _boom(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("should not call the LLM for an empty answer")

    monkeypatch.setattr(judge_module.litellm, "acompletion", _boom)
    j = asyncio.run(
        LLMJudge(model="x").evaluate(
            scenario_id="s", family="simple_search", lang="fr",
            user_turns=["hi"], answers=["", "  "], expected="results",
        )
    )
    assert j.verdict == "fail" and not called


def test_evaluate_happy_path(monkeypatch):
    async def _ok(**kwargs):
        return _resp('{"verdict":"pass","score":5,"reasoning":"good","red_flags":[]}')

    monkeypatch.setattr(judge_module.litellm, "acompletion", _ok)
    j = asyncio.run(
        LLMJudge(model="x").evaluate(
            scenario_id="s", family="compare", lang="fr",
            user_turns=["a", "b"], answers=["ans1", "ans2"], expected="compares hotels",
        )
    )
    assert j.passed and j.score == 5.0


def test_evaluate_llm_outage_is_error_not_crash(monkeypatch):
    async def _raise(**kwargs):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(judge_module.litellm, "acompletion", _raise)
    j = asyncio.run(
        LLMJudge(model="x").evaluate(
            scenario_id="s", family="faq", lang="en",
            user_turns=["q"], answers=["a"], expected="answers the policy question",
        )
    )
    assert j.verdict == "error" and "judge unavailable" in j.red_flags
