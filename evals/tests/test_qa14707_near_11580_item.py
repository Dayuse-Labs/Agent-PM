"""Offline guard for the live item `qa14707-near-11580-en` (QA14707 Q29)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from evals.langfuse_evaluators import _eval_resolved_country_code

DATASET = Path(__file__).resolve().parents[1] / "datasets" / "b2c-qa-14707-2026-10-14.jsonl"
ITEM_ID = "qa14707-near-11580-en"


def _item() -> dict:
    for line in DATASET.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if row["id"] == ITEM_ID:
                return row
    raise AssertionError(f"{ITEM_ID} missing from {DATASET.name}")


def test_message_has_bare_zip_and_names_no_country() -> None:
    item = _item()
    text = item["input"]["messages"][-1]["content"]
    assert "11580" in text
    assert not re.search(r"\b(USA|US|United States|America)\b", text, re.IGNORECASE)
    assert item["input"]["profile"] == {}
    assert item["expected_output"]["resolved_country_code"] == "US"
    assert item["metadata"]["status"] == "regression_guard"


def test_country_evaluator_passes_us_and_fails_mx() -> None:
    expected = _item()["expected_output"]
    ok = _eval_resolved_country_code(expected, {"active_filters": {"country_code": "US"}})
    bad = _eval_resolved_country_code(expected, {"active_filters": {"country_code": "MX"}})
    assert ok is not None and ok.value == 1
    assert bad is not None and bad.value == 0
