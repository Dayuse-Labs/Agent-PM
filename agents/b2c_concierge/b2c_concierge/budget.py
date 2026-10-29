"""Per-turn LLM-call budget of the b2c-concierge spine (structural invariant).

The structural budget is <= 3 LLM calls on a typical turn (audit invariant):
economy triage + the leaf's internal 0-1 call + ONE synthesis. The spine
charges the budget BEFORE each call site (an attempt consumes budget) and
charges 1 slot when a leaf leg runs (the leaf's contract allows it 0-1
internal LLM call). Exceeding the cap raises: a guard never re-runs a loop,
so a 4th call is a programming error to fail loudly on, never to retry
around.

S2: in-memory counter + one log line per turn, no message content (GDPR).
S3 plugs dayuse_agent_common metrics_pg on top of the same counter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .turn_facts import TurnFacts

MAX_LLM_CALLS_PER_TURN = 3


class LlmBudgetExceededError(RuntimeError):
    """A 4th LLM call was attempted in one turn — structural bug, fail loudly."""


@dataclass
class TurnBudget:
    """Counts the LLM-call slots spent on ONE turn; created fresh each turn.

    `fired` (OBS3): the set of `GUARD_SCORE_NAMES` entries whose trigger
    condition was met THIS turn — accumulated at each guard's own call site
    (agent.py, profile.py, inline_tools.py) and read once, at the turn's
    single emission point (`_emit_turn_metric`), into `score_guards`.

    `fallbacks`: same mechanics for `FALLBACK_SCORE_NAMES` — the degraded
    paths that still answered this turn, read into `score_fallbacks`.

    `searched_city` / `facts`: same mechanics for the widget's `turn_facts`
    (turn_facts.py) — the city a search ran on this turn, and the facts
    `_emit_turn_metric` freezes at the turn's exit.

    `dialogue` (2026-10-29): the turn's dialogue context
    (`dialogue_context.py`), read before the turn changes the profile."""

    llm_calls: int = 0
    phases: list[str] = field(default_factory=list)
    fired: set[str] = field(default_factory=set)
    fallbacks: set[str] = field(default_factory=set)
    searched_city: str | None = None
    facts: TurnFacts | None = None
    dialogue: dict[str, Any] | None = None

    def charge(self, phase: str) -> None:
        if self.llm_calls >= MAX_LLM_CALLS_PER_TURN:
            raise LlmBudgetExceededError(
                f"LLM budget exceeded: {self.llm_calls} call(s) already spent this turn, "
                f"refusing '{phase}' (max {MAX_LLM_CALLS_PER_TURN}/turn)"
            )
        self.llm_calls += 1
        self.phases.append(phase)
