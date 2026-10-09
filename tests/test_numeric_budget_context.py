"""Bare postal codes must not become spending limits before any budget question."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from b2c_concierge.budget import TurnBudget
from b2c_concierge.triage import classify


def classified(monkeypatch, message, request, previous_reply=None):
    async def completion(**kwargs):
        payload = {"family": "search", "language": "en", "requested_budget": request}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])

    monkeypatch.setattr("b2c_concierge.triage.litellm.acompletion", completion)
    return asyncio.run(classify(message, TurnBudget(), previous_reply=previous_reply))


@pytest.mark.parametrize("message", ["78240", "78239", "75008", "60"])
def test_ungrounded_bare_number_is_not_a_budget(monkeypatch, message):
    result = classified(monkeypatch, message, {
        "amount": int(message), "currency": "EUR", "unit": "total", "evidence": message,
    })
    assert result.requested_budget is None
    assert result.budget_checked  # no fallback leaf cap may take over
    assert result.budget_interpretation_unverified


@pytest.mark.parametrize("answer_to", [None, "", "What is your max budget?"])
def test_invented_prior_question_cannot_authorize_bare_amount(monkeypatch, answer_to):
    result = classified(monkeypatch, "78240", {
        "amount": 78240, "unit": "total", "evidence": "78240", "answer_to": answer_to,
    }, "Which city or postal code?")
    assert result.requested_budget is None


def test_budget_question_keeps_real_bare_answer_and_has_no_arbitrary_amount_ceiling(monkeypatch):
    question = "What is your maximum total budget in JPY?"
    result = classified(monkeypatch, "78240", {
        "amount": 78240, "unit": "total", "evidence": "78240", "answer_to": question,
    }, question)
    assert result.requested_budget["amount"] == 78240
    assert result.requested_budget["currency"] is None  # resolved separately from trusted native context
    assert not result.budget_interpretation_unverified


@pytest.mark.parametrize("message", ["$40", "40 USD", "under 40", "max 78240 JPY"])
def test_explicit_budget_is_not_blocked_by_numeric_only_guard(monkeypatch, message):
    amount = 78240 if "78240" in message else 40
    result = classified(monkeypatch, message, {
        "amount": amount, "unit": "total", "evidence": message,
    })
    assert result.requested_budget["amount"] == amount
    assert not result.budget_interpretation_unverified


def test_missing_optional_budget_key_cannot_reactivate_legacy_numeric_cap(monkeypatch):
    async def completion(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"family":"search","language":"en","bare_budget_value":78240}'
        ))])

    monkeypatch.setattr("b2c_concierge.triage.litellm.acompletion", completion)
    result = asyncio.run(classify("78240", TurnBudget()))
    assert result.requested_budget is None
    assert result.budget_checked
    assert not result.budget_interpretation_unverified
