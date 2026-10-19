---
id: Q28
title: "Anti-loop on free questions, read from the state: a third free question in a row without a search asks nothing"
phase: 5
model: opus
model_reason: "Restores a guard Q11 removed with a new state design (a count in the persisted pending_search, a no-question synthesis flag, a deterministic correction) across the spine, the profile and the templates."
effort: high
depends_on: [Q11]
parallel_batch: 5A
owned_files:
  - agents/b2c_concierge/b2c_concierge/agent.py
  - agents/b2c_concierge/b2c_concierge/profile.py
  - agents/b2c_concierge/b2c_concierge/templates.py
  - agents/b2c_concierge/tests/**
resources: []
prerequisites: [E2]
context_budget: 35%
token_estimate: 2.0M
max_turns: 50
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/b2c_concierge/tests"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/b2c_concierge/tests/test_free_question_anti_loop.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/b2c_concierge/tests/test_clarification_template.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q tests/test_leaf_concierge_seam.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "`next_pending_search` (agents/b2c_concierge/b2c_concierge/profile.py) carries an integer `asked`: the number of turns in a row that ended on a free question (a stored `last_clarifying_question` that did not come from the place template) without a search. The count starts at 1 on the first such turn. A turn with results, or with no question, ends the streak, as the slot is cleared today. No question text is compared."
  - "New test file agents/b2c_concierge/tests/test_free_question_anti_loop.py (one session, fake leaf with no results, fake synthesis, offline). A leaf that asks a free question on 4 turns in a row keeps the question on turns 1 and 2. From turn 3 (`asked` > `templates.CLARIFICATION_MAX_ASKS`), the reply's last non-empty line does not end with a question mark, `last_clarifying_question` is None, the pending request (date, slot) is kept, and `anti_clarification_loop` is in `budget.fired` on turns 3 and 4 only. On the parent commit the turn-3 reply still ends on the question: the report quotes the failing assertion and the observed value of that run."
  - "The correction stays within budget. On a corrected turn, the same and only synthesis call is told not to ask a question. If its last non-empty line still ends with a question mark (the `leaf_question` rule, no regex), that exact line is dropped. If nothing remains, a fixed template of agents/b2c_concierge/b2c_concierge/templates.py that asks nothing is used, in every language of `TEMPLATE_LANGUAGES` (agents/b2c_concierge/b2c_concierge/triage.py). One test per branch. No retry and no added LLM call; `MAX_LLM_CALLS_PER_TURN` is unchanged."
  - "Test: a stored `pending_search` whose `asked` is missing, a bool, a string or lower than 1 (a profile written by another writer) loads through `SessionProfile.from_dict` without raising and counts from 1."
  - "Test: a search turn with results between two asks resets the count. A place question (template path) does not use this count: agents/b2c_concierge/tests/test_clarification_template.py (`fired == [False, True, True]`) passes without change to its assertions."
  - "`anti_clarification_loop` stays in `GUARD_SCORE_NAMES` and no name is added to or removed from libs/b2c_common/b2c_common/scores.py. The existing test that no message content reaches a metric line is green."
  - "The mcp-dayuse#6 tests, the four tests Q11 adapted (test_spine_profile.py TestPendingSearchThroughTheSpine, test_typed_budget_spine.py TestBareNumber), the seam tests of tests/test_leaf_concierge_seam.py (Q15), the `region_anchor` tests of agents/b2c_concierge/tests/test_clarification_routing.py (Q14) and agents/b2c_concierge/tests/test_entry_market_country.py (Q16) pass without change to their assertions. If test_synthesis_question_memory.py exists, it passes without change too."
  - "No new regex or word list in the diff."
---

## Launch prompt
You carry out Q28 on the branch task/Q28. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle, the Q04 and Q11 entries), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- Q11 removed the retry-clarification-loop synthesis guard and its strip. Only the place-question anti-loop remains: agents/b2c_concierge/b2c_concierge/agent.py, search `QA14707 (decision DQ2): a place question is rendered by template`, which reads `pending_clarification.asked` (`next_pending_clarification` in profile.py, including its guard against a malformed stored count).
- `next_pending_search` and `pending_search_context` (agents/b2c_concierge/b2c_concierge/profile.py): the slot `{request, question}` and how it reaches the leaf as EARLIER REQUEST / YOU ASKED / REPLY.
- `leaf_question` (profile.py): the punctuation rule for « this line is a question ».
- `_SYNTHESIS_INSTRUCTION` and `_synthesize_with_guards` (agent.py): the single synthesis call and its guards.
- `templates.CLARIFICATION_MAX_ASKS` (templates.py) and `TEMPLATE_LANGUAGES` (triage.py).
- CLAUDE.md: a guard never relaunches a loop. At most one bounded retry, then a deterministic correction. This task uses no retry at all.
- Old production sessions repeated one question up to 7 times.

## Implementation notes
1. Count turns, not wordings: two different free questions in a row without a search are still a loop for the user.
2. The no-question instruction rides on the existing synthesis call, as an extra line in its input. Never make a second call.
3. Keep the request open: the next turn's leaf still gets EARLIER REQUEST, with no YOU ASKED.
4. The new `asked` key is part of the persisted session profile (Redis, existing TTL) and holds no message text.

## Out of scope
- The place-question anti-loop (Q04) and its templates.
- The triage prompt and `triage.py` (read `TEMPLATE_LANGUAGES` only).
- The remaining uses of `is_bare_affirmative` (S-L7).
