---
id: Q11
title: "Removal: question extracted by regex and yes/no by word list, on the clarification route"
phase: 4
model: sonnet
model_reason: "Source plan's model, kept: a bounded removal on the concierge side, replaced by Q04's structured state and Q05's closed field."
effort: medium
depends_on: [Q09]
parallel_batch: 4B
owned_files:
  - agents/b2c_concierge/b2c_concierge/profile.py
  - agents/b2c_concierge/b2c_concierge/agent.py
  - agents/b2c_concierge/tests/**
resources: []
prerequisites: [E2, H1, H3]
context_budget: 35%
token_estimate: 2.3M
max_turns: 50
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/b2c_concierge/tests"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "No regex feeds \"YOU ASKED\" any more (`extract_final_question` has no caller on that path, diff)."
  - "The decisions \"answer to the pending question\" no longer call `is_bare_affirmative`. That covers the fast path (`answers_pending`, `agent.py:1206` on `main`) and the ack branch towards the search (`:1352-1359` on `main`). Both read the triage's `answers_pending` / `affirmative` (diff)."
  - "The tests of mcp-dayuse#6 (\"piscine < 150 € demain 14h-18h\" then \"Lyon\" keeps everything; \"oui\" answers the question) pass without change to their assertions."
  - "`git grep -n pending_place -- agents libs` returns nothing, or the reader that remains is noted in a `debt` entry."
  - "No new regex or word list in the diff."
---

## Launch prompt
You carry out Q11 on the branch task/Q11. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- **The regex extraction.** `extract_final_question` (`profile.py:1063`) extracts **by regex** the last question of the synthesis's reply, and `questions_equivalent` (`:1077`) compares two questions. These two functions fill:
  - "YOU ASKED" of `pending_search`;
  - `profile.last_clarifying_question`, which the triage receives since PORT1;
  - the anti-loop (`agent.py:900-928`).
- **The word list.** `_AFFIRMATIVE_RE` (`profile.py:136`) and `is_bare_affirmative` (`:143`) are a closed list of yes/ok. « Je confirme » is not in it. Uses on `main`:
  - `agent.py:1206`: fast path `answers_pending` → **in scope**;
  - `:1352-1359`: ack + pending → search → **in scope**;
  - `:1160`: greeting relaunch → out of scope;
  - `:1505`: `search_exhausted` → out of scope.
- **`pending_place`**:
  - It is an ordinary profile field (`profile.py:280`, `:343`, `:773`), cleared at `agent.py:1714-1715`.
  - Q09, merged before this task, removed its writer on the leaf side.
- **Replacements**:
  - the structured `pending_clarification` (Q04), for the code's questions;
  - for a free question of the leaf, its **own** text, taken before the synthesis, instead of a sentence extracted from the paraphrase;
  - `answers_pending` and `affirmative` from the triage (Q05).
- **Line numbers** are those of `main`, before phase 2: Q04 and Q05 have changed these files, so search by name.

## Implementation notes
- **"YOU ASKED"** of `pending_search` receives the leaf's text as the leaf wrote it, not a sentence extracted by regex from the paraphrase. The concierge already receives that text before the synthesis, so nothing changes on the leaf side.
- **Anti-loop.** It works on the state (Q04). If `questions_equivalent` and the extraction have no caller left, delete them.
- **`pending_place`.** Remove the field from the profile (`profile.py`) and its clearing (`agent.py`), now that nothing writes it.
- **Pending-question path.** The path "answer to a pending question" no longer reads `_AFFIRMATIVE_RE`: it reads `answers_pending` and `triage.affirmative`.
- **Remaining uses.** `_AFFIRMATIVE_RE` still serves the greeting relaunch and `search_exhausted`. Leave them, and note the remaining use as `debt` (S-L7).

## Out of scope
- `_AFFIRMATIVE_RE` outside the clarification route (`:1160`, `:1505`).
- The triage's language rules (`triage.py:102-108`, `:171-179`).
