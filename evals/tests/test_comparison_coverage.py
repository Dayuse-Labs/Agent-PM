import importlib.util
import json
import sys
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[2] / "dayuse_eval_pack/eval_pack/compare.py"
spec = importlib.util.spec_from_file_location("coverage_compare", path)
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)


def test_missing_candidate_case_fails_cli_even_with_allow_regressions(tmp_path, monkeypatch):
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    before.write_text(json.dumps({"results": [{"id": "faq", "passed": True}, {"id": "cancel", "passed": True}]}))
    after.write_text(json.dumps({"results": [{"id": "faq", "passed": True}]}))
    monkeypatch.setattr(sys, "argv", ["compare", "--baseline", str(before), "--candidate", str(after),
                                     "--output", str(tmp_path / "out.json"), "--allow-regressions"])
    assert compare.main() == 1


@pytest.mark.parametrize("rows", [[], [{"id": "faq"}, {"id": "faq"}], [{}]])
def test_empty_duplicate_and_unidentified_results_cannot_pass(rows):
    with pytest.raises(ValueError):
        compare.compare_reports({"results": rows}, {"results": [{"id": "faq"}]})
