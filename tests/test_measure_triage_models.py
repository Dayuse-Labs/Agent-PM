"""The triage A/B instrument must read back exactly what `triage.classify()` sent.

`scripts/measure_triage_models.py` rebuilds `classify()`'s arguments from the
user content recorded in Langfuse traces. If `classify()` changes that layout,
the instrument would silently replay mangled inputs, so the parser is
round-tripped here through the REAL function, with litellm stubbed.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import b2c_concierge.triage as triage_module
from b2c_concierge.budget import TurnBudget

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "measure_triage_models.py"
_spec = importlib.util.spec_from_file_location("measure_triage_models", _SCRIPT)
assert _spec is not None and _spec.loader is not None
instrument = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(instrument)


def _sent_user_content(monkeypatch, message, recent, question) -> str:
    captured: dict = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])

    monkeypatch.setattr(triage_module.litellm, "acompletion", fake_acompletion)
    asyncio.run(triage_module.classify(message, TurnBudget(), recent_messages=recent,
                                       previous_question=question))
    return captured["messages"][-1]["content"]


@pytest.mark.parametrize(
    ("message", "recent", "question"),
    [
        ("un hôtel à Lyon demain", None, None),
        ("Lyon", ["un hotel avec piscine à moins de 150€ demain"], None),
        ("150", None, "Quel est votre budget maximum pour la journée ?"),
        ('il dit "ok" puis\n>>> une ligne', ["a", "b\nc", "d"], 'Lequel : « 1 » ou "2" ?'),
    ],
)
def test_parse_reads_back_what_classify_sent(monkeypatch, message, recent, question):
    content = _sent_user_content(monkeypatch, message, recent, question)
    assert instrument.parse_user_content(content) == {
        "message": message, "recent_messages": recent, "previous_question": question,
    }


def test_the_frozen_fixture_is_self_consistent():
    entries = [json.loads(line) for line in instrument.FIXTURE.read_text(encoding="utf-8").splitlines() if line]
    assert entries
    keys = [e["key"] for e in entries]
    assert len(keys) == len(set(keys))
    assert all(e["key"] == instrument.input_key(e) for e in entries)
