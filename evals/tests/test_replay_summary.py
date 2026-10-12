import json

from evals.replay_summary import summarize


def test_actual_calls_are_not_logical_budget_and_missing_cost_is_visible(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"identity":{"variant":"v"},"complete":True}))
    (tmp_path / "cases").mkdir()
    (tmp_path / "cases/one.json").write_text(json.dumps({"case_id":"one","session_id":"session","complete":True,"traffic":"unclassified",
        "turns":[{"index":1,"response":{"message":"Check your confirmation.","hotels":None},"timing_ms":{"progress":3,"total":100}}]}))
    base = {"x-replay-variant":"v","x-replay-case":"one","x-replay-turn":"1"}
    metrics = [{**base,"event_type":"llm_call","status":"ok","cost_usd":.1} for _ in range(4)]
    metrics.append({**base,"event_type":"llm_call","status":"error"})
    metrics.append({**base,"event_type":"turn","status":"ok","llm_calls":3,"family":"faq"})
    metrics.append({**base,"event_type":"llm_call","x-replay-variant":"another-run","cost_usd":10})
    report = summarize(tmp_path, metrics)
    assert report["actual_llm_call_events"] == 5
    assert report["logical_budget_calls"]["mean"] == 3
    assert report["estimated_cost_usd"] == .4
    assert report["llm_events_without_cost"] == 1
    assert report["policy_accuracy"] == "not_graded_by_this_report"
    assert report["ctr_and_conversion"] == "not_measurable_offline"
    assert report["latency_ms"].get("token") is None


def test_resumed_session_does_not_double_count_failed_attempt_as_candidate_cost(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"identity":{"variant":"v"},"complete":True}))
    (tmp_path / "cases").mkdir()
    (tmp_path / "cases/one.json").write_text(json.dumps({"case_id":"one","session_id":"new","previous_sessions":["old"],
        "complete":True,"traffic":"unclassified","turns":[{"index":1,"response":{"message":"ok"},"timing_ms":{"total":100}}]}))
    base = {"x-replay-variant":"v","x-replay-case":"one","x-replay-turn":"1","event_type":"llm_call","status":"ok"}
    report = summarize(tmp_path, [{**base,"cost_usd":.2},
        {**base,"x-replay-session-id":"old","cost_usd":.3},
        {**base,"x-replay-session-id":"new","cost_usd":.1}])
    assert report["estimated_cost_usd"] == .1
    assert report["all_attempts_estimated_cost_usd"] == .6
    assert report["actual_llm_call_events"] == 1
    assert report["resumed_sessions"] == 1
