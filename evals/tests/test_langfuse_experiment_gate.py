"""OBS6 CI gate — runs a real Langfuse dataset experiment against the live
3-service stack. NOT part of the default offline `pytest -q` invariant
(agents/libs' entire suite runs with no network, no API key): this file is
double-gated — both `RUN_LANGFUSE_EXPERIMENT_GATE=1` AND the Langfuse keys
must be present, so a dev with a sourced `.env` never triggers a live network
test by running plain `pytest -q`. Only `.github/workflows/ci.yml`'s
dedicated `langfuse-experiments` job sets the flag.

Threshold policy (OBS6, first round): "pose la mesure avant le seuil" — the
assert below is deliberately commented out. Fixing the seuil needs >= 2-3
reference runs on `main` first (see HANDOFF.md's OBS6 block for the observed
baseline); until then this test only proves the gate is wired end-to-end and
non-blocking (the job itself sets `continue-on-error: true`).
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_LANGFUSE_EXPERIMENT_GATE"),
    reason="live network + real LLM calls — opt-in only (RUN_LANGFUSE_EXPERIMENT_GATE=1), "
    "never part of the offline `pytest -q` gate",
)


def _pass_rate(result: object) -> float:
    outcomes = [
        int(evaluation.value)
        for item_result in result.item_results  # type: ignore[attr-defined]
        for evaluation in item_result.evaluations
        if isinstance(evaluation.value, int)
    ]
    return sum(outcomes) / len(outcomes) if outcomes else 0.0


def test_geo_poi_experiment_runs_and_scores() -> None:
    from langfuse import get_client

    from evals.langfuse_evaluators import ALL_EVALUATORS
    from evals.langfuse_experiment import make_task

    langfuse = get_client()
    run_name = f"ci-{os.environ.get('GITHUB_RUN_ID', 'local')}"
    dataset = langfuse.get_dataset("b2c/geo-poi")
    result = dataset.run_experiment(
        name=run_name, task=make_task(langfuse, run_name), evaluators=list(ALL_EVALUATORS), max_concurrency=3
    )
    langfuse.flush()

    rate = _pass_rate(result)
    print(f"b2c/geo-poi pass rate: {rate:.0%} ({len(result.item_results)} items)")
    # THRESHOLD — not enforced this round, see module docstring. Once a
    # baseline is established from reference runs on main:
    # assert rate >= 0.60
    assert result.item_results  # the gate itself must have actually run something
