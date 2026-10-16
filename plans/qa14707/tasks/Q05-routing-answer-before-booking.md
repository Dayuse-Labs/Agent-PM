---
id: Q05
title: "Routing: the answer to the question goes before the booking"
phase: 2
model: opus
model_reason: "Source plan's model, kept: triage (prompt and closed schema) and routing priority, with the R9 invariant at stake."
effort: high
depends_on: [Q04]
parallel_batch: 2C
owned_files:
  - agents/b2c_concierge/b2c_concierge/triage.py
  - agents/b2c_concierge/b2c_concierge/agent.py
  - agents/b2c_concierge/b2c_concierge/profile.py
  - agents/b2c_concierge/b2c_concierge/inline_tools.py
  - agents/b2c_concierge/b2c_concierge/dialogue_context.py
  - agents/b2c_concierge/tests/**
resources: []
prerequisites: [E2]
context_budget: 45%
token_estimate: 4.1M
max_turns: 70
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/b2c_concierge/tests"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Test (fake triage `{\"family\":\"booking\",\"booking_confirmation\":\"confirm\",\"answers_pending\":\"yes\"}`, clarification pending): search route, and no call to `generate_booking_link` or to `find_hotel_by_name`."
  - "Test: the same triage **without** a pending clarification, with no offer and no list, returns the \"no list\" template, as today."
  - "Test: with a pending offer, \"je confirme\" stays a booking confirmation (R9 unchanged, `guard_booking_confirmation`)."
  - "Test: option index 2 launches the search on the city of option 2."
  - "Test: the triage rejects a value of `answers_pending` outside the enumeration and falls back to `no`."
  - "Test: with a clarification pending, the acknowledgement fast path (`is_bare_affirmative`, `agent.py:1200-1212`) never applies; the turn goes through the triage."
  - "Negative control, as report evidence (the command run and its failing output): without the new priority, the first test takes the booking route."
  - "`MAX_LLM_CALLS_PER_TURN` is unchanged (diff)."
---

## Launch prompt
You carry out Q05 on the branch task/Q05. Read DISCOVERY.md and HANDOFF.md
of the plan first, then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- **Trace C2** (session `8a79b460…`, turn `a53c0b1b…`). After a question about the city, the chain went wrong:
  - « Je confirme » is triaged `{"family":"booking","booking_confirmation":"confirm"}`;
  - that leads to `generate_booking_link`;
  - then to `find_hotel_by_name("Je confirme")`, which errors;
  - then to the template `_NEEDS_SELECTION_NO_LIST` (`templates.py:364-367`).
- **What the triage sees.**
  - In prod (`cbe88b9`), the triage did not see the question asked.
  - **Since PORT1 (#137)**, it receives `LAST ASSISTANT QUESTION` = `profile.last_clarifying_question` (`triage.py:487-519`, called at `agent.py:1226`).
  - Only the budget uses it, through `answer_to`: the triage copies the question, and the code checks the quote (`triage.py:268-278`, instruction `:416-428`).
  - Its examples still push "je confirme" towards `booking` (`triage.py:392` and following).
- **Current priority** (`agent.py:1328-1362`):
  1. booking signal (`:1328`);
  2. named choice;
  3. pick;
  4. ordinal;
  5. refinement (`:1350`);
  6. pending request towards the search, **only if `family == "ack"`** (`:1353-1360`).

  `pending_search` is emptied whatever the route (`:1362`).
- **Fast path before the triage** (`agent.py:1200-1212`): a local `answers_pending`, computed **by regex** (`is_bare_affirmative`), decides whether a "yes" short-circuits the triage.
- **The triage's closed fields.** `Triage` (`triage.py:149`) already validates `family`, `affirmative`, `booking_confirmation`, `hotel_name`, `requested_budget`… It has no field for an answer to a clarification question.
- **From Q04**: `profile.pending_clarification = {clarification, request}`. A rendered template sets `profile.last_clarifying_question` to the code's text, numbered options included.

## Implementation notes
1. **Triage input: no new channel.** The pending question reaches the triage through PORT1's `previous_question`. Since Q04 it is the template's text, written by the code and no longer extracted by regex. If there are options, their numbered labels are part of that text. The triage never receives the profile (GDPR minimisation).
2. **Triage output.** Add a closed field `answers_pending ∈ {yes, no}`, default `no`, validated like the other enumerations, plus the index of the chosen option when there are options.
   - No `answer_to` copy for this field. The code already knows from the state that a clarification is pending, so a quote to check would only add a possible false negative to the routing. `answer_to` stays with the budget.
   - The triage routes; it doesn't extract the place (decision L1/D-6). There is no new LLM call.
   - The local regex `answers_pending` (`agent.py:1206`) gives way to the state: with a clarification pending, the acknowledgement fast path never applies, and the turn goes through the triage.
3. **Priority in code.** A pending clarification with `answers_pending=yes` → search route, with Q04's context, **before** the booking route deduced from the triage.
   - Only a real booking signal goes first, that is a pending offer (`pending_booking`).
   - The condition `family == "ack"` disappears from this path.
4. **Chosen option.** An option index resolves the option's city in code, then launches the search. The city reaches the leaf without any leaf change: set the profile's `city`/`zone` before the call, and the leaf's carry-over fills them in (`inject_profile_geo_context`, `geocode_tool.py:1004-1009`).
5. **R9 invariant, strengthened.**
   - The booking route requires a pending offer or a list on screen. Otherwise: if a clarification is pending, the message is an answer; if not, the current "no list" template, unchanged.
   - `find_hotel_by_name` is only called with a `hotel_name` that came from the triage, never with the raw message (`_extract_hotel_name_candidate`, `inline_tools.py:146`).
6. **Triage prompt.** Adjust its examples: "je confirme" is a booking confirmation only when it answers a booking confirmation request. The triage prompt is not measured offline (HANDOFF PORT1); the live replay H3 measures it.

## Out of scope
- Extracting the place from the answer (Q07, done by the leaf).
- Removing `_AFFIRMATIVE_RE` (Q11).
