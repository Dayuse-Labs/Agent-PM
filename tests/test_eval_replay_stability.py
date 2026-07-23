"""Offline tests for scripts/eval_replay_stability.py (S-G8 item 8).

`compute_stability` and `critical_suite_case_ids` are pure/read-only and
tested directly. The subprocess orchestration (`invoke_runner_subprocess`,
`replay`) is tested by injecting a fake invoker — no network, no live
services, no actual `eval_pack.runner` subprocess spawned.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "eval_replay_stability.py"
_spec = importlib.util.spec_from_file_location("eval_replay_stability", _SCRIPT)
assert _spec is not None and _spec.loader is not None
ers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ers)


def _report(rows):
    return {"summary": {}, "results": [{"id": cid, "suite": suite, "passed": passed} for cid, suite, passed in rows]}


# --- critical_suite_case_ids: derived from the real fixtures, never hand-picked --
def test_critical_suite_case_ids_matches_known_81_case_gate():
    ids = ers.critical_suite_case_ids()
    assert len(ids) == 81
    assert len(set(ids)) == 81  # no duplicates across the 3 suite files


def test_critical_suite_case_ids_only_from_the_three_suites(tmp_path):
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    (cases_dir / "geo.jsonl").write_text(json.dumps({"id": "geo-1"}) + "\n", encoding="utf-8")
    (cases_dir / "multiturn.jsonl").write_text(json.dumps({"id": "mt-1"}) + "\n", encoding="utf-8")
    (cases_dir / "prod_wounds.jsonl").write_text(json.dumps({"id": "pw-1"}) + "\n", encoding="utf-8")
    (cases_dir / "core.jsonl").write_text(json.dumps({"id": "core-1"}) + "\n", encoding="utf-8")
    ids = ers.critical_suite_case_ids(cases_dir)
    assert set(ids) == {"geo-1", "mt-1", "pw-1"}


# --- compute_stability ------------------------------------------------------------
def test_compute_stability_all_stable():
    reports = [
        _report([("a", "geo", True), ("b", "geo", False)]),
        _report([("a", "geo", True), ("b", "geo", False)]),
        _report([("a", "geo", True), ("b", "geo", False)]),
    ]
    stability = ers.compute_stability(reports)
    assert stability["stability_rate"] == 1.0
    assert stability["unstable_case_ids"] == []
    assert stability["incomplete_case_ids"] == []
    assert stability["by_suite"] == {"geo": {"total": 2, "unstable": 0}}


def test_compute_stability_flags_flaky_case():
    reports = [
        _report([("a", "geo", True)]),
        _report([("a", "geo", False)]),
        _report([("a", "geo", True)]),
    ]
    stability = ers.compute_stability(reports)
    assert stability["unstable_case_ids"] == ["a"]
    assert stability["per_case"]["a"]["pass_count"] == 2
    assert stability["stability_rate"] == 0.0


def test_compute_stability_reports_incomplete_case_never_as_stable_or_unstable():
    reports = [
        _report([("a", "geo", True), ("b", "geo", True)]),
        _report([("a", "geo", True)]),  # "b" missing from this run
        _report([("a", "geo", True), ("b", "geo", True)]),
    ]
    stability = ers.compute_stability(reports)
    assert stability["incomplete_case_ids"] == ["b"]
    assert stability["unstable_case_ids"] == []  # "b" is incomplete, not unstable
    assert stability["complete_cases"] == 1
    assert stability["stability_rate"] == 1.0  # only "a" counted, and it's stable


def test_compute_stability_empty_reports():
    stability = ers.compute_stability([])
    assert stability["stability_rate"] == 0.0
    assert stability["total_cases"] == 0


# --- replay: orchestration wiring with an injected fake invoker --------------------
def test_replay_writes_and_aggregates_n_runs(tmp_path):
    calls = []

    def fake_invoker(endpoint, case_ids, output_path, api_key, timeout):
        calls.append((endpoint, tuple(case_ids), str(output_path), api_key, timeout))
        output_path.write_text(json.dumps(_report([("a", "geo", True)])), encoding="utf-8")
        return output_path

    stability = ers.replay(
        endpoint="http://127.0.0.1:8100/v3/chat",
        output_dir=tmp_path,
        runs=3,
        case_ids=["a"],
        invoker=fake_invoker,
    )
    assert len(calls) == 3
    assert all(c[0] == "http://127.0.0.1:8100/v3/chat" for c in calls)
    assert stability["stability_rate"] == 1.0
    assert (tmp_path / "replay_1.json").exists()
    assert (tmp_path / "replay_3.json").exists()


def test_replay_defaults_to_critical_suite_ids_when_none_given(tmp_path):
    seen_ids = []

    def fake_invoker(endpoint, case_ids, output_path, api_key, timeout):
        seen_ids.append(case_ids)
        output_path.write_text(json.dumps(_report([])), encoding="utf-8")
        return output_path

    ers.replay(endpoint="http://x", output_dir=tmp_path, runs=1, invoker=fake_invoker)
    assert len(seen_ids[0]) == 81


# --- invoke_runner_subprocess: argv construction only, subprocess.run stubbed -----
def test_invoke_runner_subprocess_builds_expected_argv(monkeypatch, tmp_path):
    captured = {}

    def fake_run(args, cwd, check):
        captured["args"] = args
        captured["cwd"] = cwd
        captured["check"] = check

    monkeypatch.setattr(ers.subprocess, "run", fake_run)
    output_path = tmp_path / "run.json"
    ers.invoke_runner_subprocess("http://127.0.0.1:8100/v3/chat", ["geo-1", "geo-2"], output_path, api_key="secret", timeout=45)

    args = captured["args"]
    assert "-u" in args
    assert "eval_pack.runner" in args
    assert "--endpoint" in args and "http://127.0.0.1:8100/v3/chat" in args
    assert "--ids" in args and "geo-1,geo-2" in args
    assert "--timeout" in args and "45" in args
    assert "--api-key" in args and "secret" in args
    assert "--output" in args and str(output_path) in args
    assert captured["cwd"] == str(ers.EVAL_PACK_DIR)
    assert captured["check"] is True


def test_invoke_runner_subprocess_omits_api_key_when_blank(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(ers.subprocess, "run", lambda args, cwd, check: captured.update(args=args))
    ers.invoke_runner_subprocess("http://x", ["geo-1"], tmp_path / "run.json")
    assert "--api-key" not in captured["args"]
