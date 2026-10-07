import json

import pytest

from evals.current_production_comparison import load_verified_pairs, render
from evals.production_replay import digest


@pytest.fixture
def pilot(tmp_path):
    source = {"id": "case", "turns": [{"row_id": 7, "body": {"message": "<script>search()</script>"}}]}
    manifest = {"complete": True, "expected_sessions_per_variant": 1, "expected_turns_per_variant": 1,
                "reference": {"sha": "production", "model_config": "prod-model"},
                "new_agent": {"sha": "new-main", "model": "new-model"}}
    (tmp_path / "pilot-manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "pilot-inputs.json").write_text(json.dumps({"cases": [source]}))
    (tmp_path / "pilot-review.json").write_text(json.dumps({
        "reference": manifest["reference"], "new_agent": manifest["new_agent"],
        "deployment_verified_before_run": True, "deployment_verified_after_run": True,
    }))
    for variant in ("production", "new_main"):
        directory = tmp_path / variant
        directory.mkdir()
        sid = f"codex-{variant}"
        value = {"case_id": "case", "input_hash": digest(source), "complete": True,
                 "session_id": sid, "turns": [{"index": 1, "row_id": 7, "response": {
                     "session_id": sid, "message": '<img src=x onerror="bad()">', "hotels": [],
                 }}]}
        (directory / "case.json").write_text(json.dumps(value))
    return tmp_path


def mutate(pilot, change):
    path = pilot / "new_main/case.json"
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))


@pytest.mark.parametrize("change", [
    lambda x: x.update(input_hash="another conversation"),
    lambda x: x.update(complete=False),
    lambda x: x.update(error={"type": "timeout"}),
    lambda x: x["turns"][0].update(row_id=8),
    lambda x: x["turns"][0]["response"].update(session_id="someone-else"),
    lambda x: x["turns"][0]["response"].update(duplicate_of_previous_turn=True),
    lambda x: x["turns"].clear(),
])
def test_complete_label_does_not_hide_invalid_pair(pilot, change):
    mutate(pilot, change)
    with pytest.raises(ValueError):
        load_verified_pairs(pilot)


def test_extra_output_cannot_silently_change_the_cohort(pilot):
    (pilot / "production/extra.json").write_text("{}")
    with pytest.raises(ValueError):
        load_verified_pairs(pilot)


def test_render_escapes_untrusted_dialogue_and_keeps_empty_cards_unscored(pilot):
    output = pilot / "report.html"
    result = render(pilot, output)
    page = output.read_text()
    assert result["turns_per_agent"] == 1
    assert "<script>" not in page and "<img src=x" not in page
    assert "&lt;script&gt;search()&lt;/script&gt;" in page
    assert page.count("ni succès ni échec automatique") == 2
    assert page.count("<article>") == 2


def test_unverified_current_deployment_cannot_be_presented_as_verified(pilot):
    path = pilot / "pilot-review.json"
    data = json.loads(path.read_text())
    data["deployment_verified_after_run"] = False
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        render(pilot, pilot / "report.html")


def test_report_uses_reviewed_scope_and_does_not_invent_pilot_incident(pilot):
    path = pilot / "pilot-review.json"
    data = json.loads(path.read_text())
    data.update(scope_note="Photographie partielle, campagne en cours.", findings=["<script>bad()</script>"])
    path.write_text(json.dumps(data))
    render(pilot, pilot / "report.html")
    page = (pilot / "report.html").read_text()
    assert "Photographie partielle, campagne en cours." in page
    assert "&lt;script&gt;bad()&lt;/script&gt;" in page
    assert "premier appel du nouvel agent a subi un timeout" not in page
    assert "<script>" not in page


def test_isolated_support_is_not_labelled_as_the_production_endpoint(pilot):
    for filename in ["pilot-manifest.json", "pilot-review.json"]:
        path = pilot / filename
        data = json.loads(path.read_text())
        data["reference"].update(mode="isolated support", endpoint="http://127.0.0.1:8355/v3/chat")
        path.write_text(json.dumps(data))
    render(pilot, pilot / "report.html")
    page = (pilot / "report.html").read_text()
    assert "Code de production · support isolé" in page
    assert "http://127.0.0.1:8355/v3/chat" in page
    assert "ai.dayuse.com" not in page
