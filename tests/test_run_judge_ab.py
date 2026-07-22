"""Offline tests for scripts/run_judge_ab.py (S-D of the agent-usa vs
AgentB2C comparative audit). No network, no litellm — HttpChatClient is
exercised via a mocked `urllib.request.urlopen`; the judge-orchestration
logic is exercised via a fake judge object (anything with an async
`.evaluate(**kwargs) -> Judgment`-shaped return + `.to_dict()`).

Loads the script by path (it's a script, not a package) — same technique as
evals/tests/test_release_gate.py loads scripts/run_release_gate.py.
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import patch

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_judge_ab.py"
_spec = importlib.util.spec_from_file_location("run_judge_ab", _SCRIPT_PATH)
run_judge_ab_module = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
# Registering in sys.modules BEFORE exec is required here (unlike
# run_release_gate.py's loader): dataclasses' `@dataclass` decorator resolves
# `cls.__module__` via sys.modules while executing the class body.
sys.modules[_spec.name] = run_judge_ab_module
_spec.loader.exec_module(run_judge_ab_module)

HttpChatClient = run_judge_ab_module.HttpChatClient
session_id_for = run_judge_ab_module.session_id_for
replay_scenario = run_judge_ab_module.replay_scenario
judge_scenario = run_judge_ab_module.judge_scenario
run_judge_ab = run_judge_ab_module.run_judge_ab
run_judge_ab_sync = run_judge_ab_module.run_judge_ab_sync
summarize_judge_ab = run_judge_ab_module.summarize_judge_ab
build_report = run_judge_ab_module.build_report
main = run_judge_ab_module.main


# --- HttpChatClient ---------------------------------------------------------------------------


class _FakeHttpResponse:
    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_send_posts_session_id_and_message_body():
    seen = {}

    def _fake(request, timeout=None):
        seen["body"] = json.loads(request.data.decode("utf-8"))
        seen["headers"] = dict(request.headers)
        return _FakeHttpResponse(json.dumps({"message": "hi"}).encode("utf-8"))

    with patch("urllib.request.urlopen", _fake):
        client = HttpChatClient(endpoint="http://x/v3/chat")
        result = client.send(session_id="sess-1", message="hello")

    assert seen["body"] == {"session_id": "sess-1", "message": "hello"}
    assert result["message"] == "hi"
    assert result["_http_status"] == 200


def test_send_always_includes_dayuse_synthetic_header():
    seen = {}

    def _fake(request, timeout=None):
        seen["headers"] = dict(request.headers)
        return _FakeHttpResponse(b"{}")

    with patch("urllib.request.urlopen", _fake):
        HttpChatClient(endpoint="http://x/v3/chat").send(session_id="s", message="m")

    assert seen["headers"].get("X-dayuse-synthetic") == "1" or seen["headers"].get("X-Dayuse-synthetic") == "1"


def test_send_includes_api_key_header_only_when_configured():
    seen = {}

    def _fake(request, timeout=None):
        seen["headers"] = dict(request.headers)
        return _FakeHttpResponse(b"{}")

    with patch("urllib.request.urlopen", _fake):
        HttpChatClient(endpoint="http://x/v3/chat", api_key="secret").send(session_id="s", message="m")
    assert seen["headers"].get("X-internal-api-key") == "secret"

    with patch("urllib.request.urlopen", _fake):
        HttpChatClient(endpoint="http://x/v3/chat").send(session_id="s", message="m")
    assert "X-internal-api-key" not in seen["headers"]


def test_send_merges_extra_headers():
    seen = {}

    def _fake(request, timeout=None):
        seen["headers"] = dict(request.headers)
        return _FakeHttpResponse(b"{}")

    with patch("urllib.request.urlopen", _fake):
        HttpChatClient(endpoint="http://x/v3/chat", extra_headers={"X-Custom": "yes"}).send(
            session_id="s", message="m"
        )
    assert seen["headers"].get("X-custom") == "yes"


def test_send_http_error_returns_dict_not_raise():
    def _fake(request, timeout=None):
        raise urllib.error.HTTPError("http://x", 503, "Service Unavailable", {}, io.BytesIO(b'{"error":"down"}'))

    with patch("urllib.request.urlopen", _fake):
        result = HttpChatClient(endpoint="http://x/v3/chat").send(session_id="s", message="m")

    assert result["_http_status"] == 503
    assert "_http_error" in result


def test_send_connection_failure_returns_dict_not_raise():
    def _fake(request, timeout=None):
        raise ConnectionRefusedError("refused")

    with patch("urllib.request.urlopen", _fake):
        result = HttpChatClient(endpoint="http://x/v3/chat").send(session_id="s", message="m")

    assert result["_http_status"] is None
    assert "_http_error" in result


def test_probe_true_on_any_http_response_even_error_status():
    # A real urlopen raises HTTPError for non-2xx — that still proves the
    # server is up, which is exactly what probe() should treat as reachable.
    def _fake(request, timeout=None):
        raise urllib.error.HTTPError("http://x", 500, "Internal Server Error", {}, io.BytesIO(b"{}"))

    with patch("urllib.request.urlopen", _fake):
        ok, reason = HttpChatClient(endpoint="http://x/v3/chat").probe()
    assert ok is True
    assert "500" in reason


def test_probe_false_on_connection_failure():
    def _fake(request, timeout=None):
        raise TimeoutError("timed out")

    with patch("urllib.request.urlopen", _fake):
        ok, reason = HttpChatClient(endpoint="http://x/v3/chat").probe()
    assert ok is False


# --- session_id_for ----------------------------------------------------------------------------


def test_session_id_for_has_canonical_eval_prefix():
    sid = session_id_for("simple_search-abc123")
    assert sid.startswith("canonical-eval-simple_search-abc123-")


def test_session_id_for_truncates_long_scenario_ids():
    long_id = "x" * 100
    sid = session_id_for(long_id)
    assert sid == f"canonical-eval-{'x' * 40}-{sid.rsplit('-', 1)[1]}"


def test_session_id_for_differs_across_calls():
    assert session_id_for("same-id") != session_id_for("same-id")


# --- replay_scenario -----------------------------------------------------------------------


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def send(self, *, session_id, message):
        self.calls.append((session_id, message))
        return self._responses.pop(0)


def test_replay_scenario_calls_client_once_per_turn_same_session_id():
    scenario = {"id": "s1", "family": "simple_search", "lang": "fr", "user_turns": ["a", "b"]}
    client = _FakeClient([{"message": "r1", "_http_status": 200}, {"message": "r2", "_http_status": 200}])

    replay = replay_scenario(scenario, client=client)

    assert len(client.calls) == 2
    assert client.calls[0][0] == client.calls[1][0]  # same session id
    assert [t["answer"] for t in replay["turns"]] == ["r1", "r2"]


def test_replay_scenario_failed_turn_yields_empty_answer_without_aborting():
    scenario = {"id": "s1", "family": "simple_search", "lang": "fr", "user_turns": ["a", "b"]}
    client = _FakeClient(
        [{"_http_status": None, "_http_error": "boom"}, {"message": "ok", "_http_status": 200}]
    )

    replay = replay_scenario(scenario, client=client)

    assert replay["turns"][0]["answer"] == ""
    assert replay["turns"][0]["error"] == "boom"
    assert replay["turns"][1]["answer"] == "ok"


# --- judge_scenario / run_judge_ab (fake judge, no litellm) ---------------------------------


class _FakeJudgment:
    def __init__(self, verdict="pass", score=4.0):
        self.verdict = verdict
        self.score = score

    def to_dict(self):
        return {"verdict": self.verdict, "score": self.score, "reasoning": "fake", "red_flags": []}


class _FakeJudge:
    def __init__(self, verdict="pass", score=4.0):
        self.calls = []
        self._verdict = verdict
        self._score = score

    async def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeJudgment(self._verdict, self._score)


def test_judge_scenario_calls_judge_with_scenario_answers_and_expected():
    scenario = {"id": "s1", "family": "compare", "lang": "fr", "user_turns": ["a"], "expected": "does X"}
    replay = {"scenario_id": "s1", "family": "compare", "lang": "fr", "turns": [{"user": "a", "answer": "reply"}]}
    judge = _FakeJudge()

    result = asyncio.run(judge_scenario(replay, scenario, judge=judge))

    assert judge.calls[0]["answers"] == ["reply"]
    assert judge.calls[0]["expected"] == "does X"
    assert result["judgment"]["verdict"] == "pass"


def test_run_judge_ab_aggregates_multiple_scenarios():
    scenarios = [
        {"id": "a-1", "family": "simple_search", "lang": "fr", "user_turns": ["hi"], "expected": "e"},
        {"id": "b-1", "family": "compare", "lang": "fr", "user_turns": ["hi"], "expected": "e"},
    ]
    client = _FakeClient([{"message": "r", "_http_status": 200}, {"message": "r", "_http_status": 200}])
    judge = _FakeJudge()

    report = run_judge_ab_sync(scenarios, client=client, judge=judge)

    assert report["summary"]["total"] == 2
    assert len(report["results"]) == 2
    assert len(judge.calls) == 2


# --- summarize_judge_ab (pure) ---------------------------------------------------------------


def _result(family, verdict, score):
    return {"family": family, "judgment": {"verdict": verdict, "score": score}}


def test_summarize_judge_ab_computes_pass_rate_and_mean_score_per_family():
    results = [
        _result("simple_search", "pass", 5),
        _result("simple_search", "fail", 1),
        _result("compare", "pass", 4),
    ]
    summary = summarize_judge_ab(results)

    assert summary["total"] == 3
    assert summary["by_family"]["simple_search"]["count"] == 2
    assert summary["by_family"]["simple_search"]["passed"] == 1
    assert summary["by_family"]["simple_search"]["pass_rate"] == 0.5
    assert summary["by_family"]["simple_search"]["mean_score"] == 3.0
    assert summary["by_family"]["compare"]["pass_rate"] == 1.0
    assert summary["overall"]["count"] == 3


def test_summarize_judge_ab_empty_results_no_crash():
    summary = summarize_judge_ab([])
    assert summary["total"] == 0
    assert summary["overall"] == {"count": 0, "passed": 0, "pass_rate": 0.0, "mean_score": 0.0}
    assert summary["by_family"] == {}


# --- build_report -----------------------------------------------------------------------------


def test_build_report_includes_metadata_and_schema_version():
    report = build_report(
        {"total": 0, "overall": {}, "by_family": {}},
        [],
        endpoint="http://x/v3/chat",
        judge_model="gpt-4o-mini",
        generated_at="2026-07-22T00:00:00+00:00",
        label="candidate",
    )
    assert report["schema_version"] == "judge-ab-v0"
    assert report["endpoint"] == "http://x/v3/chat"
    assert report["judge_model"] == "gpt-4o-mini"
    assert report["label"] == "candidate"


# --- main() (CLI) -----------------------------------------------------------------------------


def test_main_returns_2_without_openai_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def _boom(*a, **kw):
        raise AssertionError("should not be called")

    monkeypatch.setattr(run_judge_ab_module, "run_judge_ab_sync", _boom)
    rc = main(["--endpoint", "http://127.0.0.1:9999/v3/chat", "--out", str(tmp_path / "out.json")])
    assert rc == 2


def test_main_returns_2_when_no_scenarios_match(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    import evals.battery as battery_module

    monkeypatch.setattr(battery_module, "load_scenarios", lambda *a, **kw: [])
    rc = main(
        [
            "--endpoint",
            "http://127.0.0.1:9999/v3/chat",
            "--families",
            "nonexistent_family",
            "--out",
            str(tmp_path / "out.json"),
        ]
    )
    assert rc == 2


def test_main_returns_2_when_endpoint_unreachable_never_runs_judge(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    monkeypatch.setattr(HttpChatClient, "probe", lambda self, **kw: (False, "connection refused"))

    def _boom(*a, **kw):
        raise AssertionError("should not be called when endpoint is unreachable")

    monkeypatch.setattr(run_judge_ab_module, "run_judge_ab_sync", _boom)
    rc = main(
        ["--endpoint", "http://127.0.0.1:9999/v3/chat", "--limit", "1", "--out", str(tmp_path / "out.json")]
    )
    assert rc == 2


def test_main_returns_0_and_writes_report_on_success(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(HttpChatClient, "probe", lambda self, **kw: (True, "http 200"))

    canned = {
        "summary": {"total": 1, "overall": {"count": 1, "passed": 1, "pass_rate": 1.0, "mean_score": 5.0}, "by_family": {}},
        "results": [],
    }
    monkeypatch.setattr(run_judge_ab_module, "run_judge_ab_sync", lambda *a, **kw: canned)

    out_path = tmp_path / "out.json"
    rc = main(
        [
            "--endpoint",
            "http://127.0.0.1:9999/v3/chat",
            "--limit",
            "1",
            "--label",
            "candidate",
            "--out",
            str(out_path),
        ]
    )

    assert rc == 0
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["summary"]["total"] == 1
    assert written["label"] == "candidate"
