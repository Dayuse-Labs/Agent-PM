---
id: Q27
title: "A follow-up question only the synthesis asks is still remembered for the next turn"
phase: 4
model: sonnet
model_reason: "One fallback in the concierge's post-synthesis step that reuses the existing leaf_question rule, plus offline spine tests; no contract or design choice."
effort: medium
depends_on: [Q11]
parallel_batch: 4C
owned_files:
  - agents/b2c_concierge/b2c_concierge/agent.py
  - agents/b2c_concierge/b2c_concierge/profile.py
  - agents/b2c_concierge/tests/**
resources: []
prerequisites: [E2]
context_budget: 30%
token_estimate: 1.2M
max_turns: 40
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/b2c_concierge/tests"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/b2c_concierge/tests/test_synthesis_question_memory.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q tests/test_leaf_concierge_seam.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "New test file agents/b2c_concierge/tests/test_synthesis_question_memory.py (fake leaf, fake synthesis, offline). When the leaf's text asks nothing (`leaf_question` returns None) and the user-facing synthesis ends on a line that ends with a question mark, `profile.last_clarifying_question` and `profile.pending_search[\"question\"]` equal that last line, read by the same `leaf_question` rule (same 300-char cap). On the parent commit both are None: the report quotes the failing assertion and the observed value of that run."
  - "Test: on the next turn, a bare « oui » reaches the triage with that question as `previous_question` (the fake triage records its input), and the leaf's context text carries it after `YOU ASKED:`."
  - "Test: when the leaf asked a question, the leaf's line wins over the synthesis's. The test of test_spine.py that stores « Would you like hotels closer to the centre? » and the four tests Q11 adapted (test_spine_profile.py TestPendingSearchThroughTheSpine, test_typed_budget_spine.py TestBareNumber.test_a_bare_number_answering_a_budget_question_is_never_auto_widened) pass without change to their assertions."
  - "Test: a synthesis that does not end on a question mark stores None. The template paths keep the text they store today: place clarification (`next_pending_clarification`), comparison notice, party composition and budget follow-up. agents/b2c_concierge/tests/test_clarification_template.py and agents/b2c_concierge/tests/test_typed_budget_spine.py pass without change to their assertions."
  - "Test: after a question asked only by the synthesis, « oui » with a fake triage `{\"family\":\"booking\",\"booking_confirmation\":\"confirm\"}` and no pending offer calls neither `generate_booking_link` nor `find_hotel_by_name` (R9)."
  - "No new regex or word list in the diff. `MAX_LLM_CALLS_PER_TURN` is unchanged and no LLM call is added: the fallback reads the synthesis text already produced, after its guards."
  - "The seam tests of tests/test_leaf_concierge_seam.py (Q15), the `region_anchor` tests of agents/b2c_concierge/tests/test_clarification_routing.py (Q14) and agents/b2c_concierge/tests/test_entry_market_country.py (Q16) pass without change to their assertions. The existing test that no message content reaches a metric line is green."
  - "No assertion of an existing test is changed. If one asserted None after a question asked only by the synthesis, the report names it with file:line and the reason, and that test's input stays unchanged."
  - "The docstring of `leaf_question`, or of the helper that applies it to the synthesis, says what is read: the leaf's last line first, then the synthesis's last line, by punctuation only."
---

## Launch prompt
You carry out Q27 on the branch task/Q27. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle, the Q04, Q05 and Q11 entries), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- `leaf_question` (agents/b2c_concierge/b2c_concierge/profile.py, search `Question the leaf asked (QA14707, Q11)`): the leaf's last non-empty line, kept only when it ends with '?', capped at 300 characters.
- agents/b2c_concierge/b2c_concierge/agent.py, search `QA14707 (Q11): what the next turn answers`: where `last_clarifying_question` is set from the leaf's text, before the synthesis.
- The same file, search `synth = await self._synthesize_with_guards(`: the synthesis result. Right after it come `budget_followup`, which overrides the stored question, and `next_pending_search(earlier, message, "results" in response, profile.last_clarifying_question)`.
- The triage receives `previous_question` from `profile.last_clarifying_question` (PORT1).
- Q11's report: a question only the synthesis writes was no longer remembered, so a following « oui » reached the triage with no previous question.

## Implementation notes
1. The leaf's question wins. Only when the leaf asked nothing and the turn went through the synthesis, apply `leaf_question` to the final user-facing synthesis text (after its guards) and store the result.
2. Do not touch the template paths: each keeps the text it stores today.
3. Reuse `leaf_question` as it is. Do not add a regex, a word list or a second rule.

## Out of scope
- The free-question anti-loop (a separate decision).
- The triage prompt and `triage.py`.
- The remaining uses of `is_bare_affirmative` (S-L7).
