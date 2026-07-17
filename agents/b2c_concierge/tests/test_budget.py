"""The per-turn LLM budget is a structural guard: hard cap at 3, loud failure beyond."""
import pytest

from b2c_concierge.budget import MAX_LLM_CALLS_PER_TURN, LlmBudgetExceededError, TurnBudget


class TestTurnBudget:
    def test_cap_is_three(self):
        assert MAX_LLM_CALLS_PER_TURN == 3

    def test_charges_accumulate_with_phases(self):
        budget = TurnBudget()
        budget.charge("triage")
        budget.charge("leaf_llm")
        budget.charge("synthesis")
        assert budget.llm_calls == 3
        assert budget.phases == ["triage", "leaf_llm", "synthesis"]

    def test_fourth_call_raises(self):
        budget = TurnBudget()
        for phase in ("triage", "leaf_llm", "synthesis"):
            budget.charge(phase)
        with pytest.raises(LlmBudgetExceededError, match="extra"):
            budget.charge("extra")
        # A refused charge must not have been counted.
        assert budget.llm_calls == 3
