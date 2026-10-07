import json

import pytest

from evals.production_replay import digest
from evals.replay_comparison import compare


def source(cid, split="holdout"):
    return {"id": cid, "split": split, "traffic": "unclassified", "turns": [{"row_id": cid + "-1"}]}


def run(tmp_path, name, expected, saved=None, manifest_complete=True):
    path = tmp_path / name
    (path / "cases").mkdir(parents=True)
    manifest = {"complete": manifest_complete, "identity": {"variant": name, "concurrency": 4,
        "cases_hash": digest(expected), "provenance": {"corpus_sha256": "sha", "code_sha": name,
        "model": "same-model", "inventory_day": "2026-10-08"}}}
    (path / "manifest.json").write_text(json.dumps(manifest))
    for c in expected if saved is None else saved:
        case = {"case_id": c["id"], "input_hash": digest(c), "split": c["split"], "traffic": c["traffic"],
            "complete": True, "session_id": name + c["id"], "turns": [{"index": 1, "row_id": c["turns"][0]["row_id"],
            "response": {"message": "Check your confirmation.", "hotels": None}, "timing_ms": {"total": 10}}]}
        (path / "cases" / (c["id"] + ".json")).write_text(json.dumps(case))
    return path


def edit(path, file, mutate):
    data = json.loads((path / file).read_text())
    mutate(data)
    (path / file).write_text(json.dumps(data))


def test_only_paired_complete_cases_count_even_if_manifest_falsely_claims_completion(tmp_path):
    expected = [source("one"), source("two", "dev")]
    baseline = run(tmp_path, "base", expected)
    candidate = run(tmp_path, "new", expected, saved=expected[:1])
    result = compare(baseline, candidate, expected, "sha", [])
    assert result["comparison_complete"] is False
    assert result["coverage"]["unpaired_sessions"] == 1
    assert result["paired_cohorts"]["all"]["baseline"]["turns"] == 1
    assert result["paired_cohorts"]["split:dev"]["baseline"]["turns"] == 0
    assert result["paired_cohorts"]["all"]["paired_flag_transitions"]["non_ok_turn_status"] == {"unscored_metric_coverage": 1}


@pytest.mark.parametrize("mutation", [
    lambda c: c.update(input_hash="wrong"),
    lambda c: c.update(split="dev"),
    lambda c: c.update(turns=[]),
    lambda c: c["turns"][0].update(row_id="wrong"),
    lambda c: c["turns"][0].update(index=2),
    lambda c: c.update(error={"type": "ReadError"}),
])
def test_corrupted_or_wrong_inputs_cannot_validate_a_run(tmp_path, mutation):
    expected = [source("one")]
    baseline, candidate = run(tmp_path, "base", expected), run(tmp_path, "new", expected)
    edit(candidate, "cases/one.json", mutation)
    with pytest.raises(ValueError):
        compare(baseline, candidate, expected, "sha", [])


def test_duplicate_checkpoints_and_changed_model_are_rejected(tmp_path):
    expected = [source("one")]
    baseline, candidate = run(tmp_path, "base", expected), run(tmp_path, "new", expected)
    duplicate = candidate / "cases/copy.json"
    duplicate.write_bytes((candidate / "cases/one.json").read_bytes())
    with pytest.raises(ValueError, match="duplicate"):
        compare(baseline, candidate, expected, "sha", [])
    duplicate.unlink()
    edit(candidate, "manifest.json", lambda m: m["identity"]["provenance"].update(model="other-model"))
    with pytest.raises(ValueError, match="model"):
        compare(baseline, candidate, expected, "sha", [])


def test_superseded_revision_is_not_a_final_candidate(tmp_path):
    expected = [source("one")]
    baseline, candidate = run(tmp_path, "base", expected), run(tmp_path, "new", expected)
    (candidate / "SUPERSEDED.json").write_text("{}")
    with pytest.raises(ValueError, match="superseded"):
        compare(baseline, candidate, expected, "sha", [])


def test_resumed_attempt_cost_and_missing_turn_metrics_are_not_hidden(tmp_path):
    expected = [source("one")]
    baseline, candidate = run(tmp_path, "base", expected), run(tmp_path, "new", expected)
    edit(candidate, "cases/one.json", lambda c: c.update(previous_sessions=["old"]))
    key = {"x-replay-variant": "new", "x-replay-case": "one", "x-replay-turn": "1", "event_type": "llm_call"}
    metrics = [{**key, "x-replay-session-id": "old", "cost_usd": 10},
               {**key, "cost_usd": 20},
               {**key, "x-replay-session-id": "newone", "cost_usd": .1}]
    result = compare(baseline, candidate, expected, "sha", metrics)
    assert result["comparison_complete"] is True
    assert result["release_approved"] is False
    assert result["policy_accuracy"] == "not_graded"
    observed = result["paired_cohorts"]["all"]["candidate"]
    assert observed["observed_estimated_cost_usd"] == .1
    assert observed["actual_llm_call_events"] == 1
    assert observed["turns_missing_or_duplicating_metrics"] == 1


def test_more_hotel_results_is_not_labelled_a_quality_win(tmp_path):
    expected = [source("one")]
    baseline, candidate = run(tmp_path, "base", expected), run(tmp_path, "new", expected)
    edit(candidate, "cases/one.json", lambda c: c["turns"][0]["response"].update(hotels=[{"id": 1}]))
    result = compare(baseline, candidate, expected, "sha", [])
    assert result["paired_cohorts"]["all"]["paired_flag_transitions"]["has_results"] == {"0->1": 1}
    assert result["release_approved"] is False
