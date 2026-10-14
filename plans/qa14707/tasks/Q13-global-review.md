---
id: Q13
title: Global review (read-only)
phase: 5
model: opus
model_reason: "Source plan's model, kept: a skeptical review of the whole plan, read-only."
effort: high
depends_on: [Q12]
parallel_batch: 5B
owned_files: []
resources: []
prerequisites: [E2]
context_budget: 40%
token_estimate: 2.6M
max_turns: 50
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Review report: each of the 10 points below marked OK, or KO with its evidence (file:line, command)."
  - "Each KO is written up as a `review` or `debt` entry for the plan's HANDOFF."
  - "No file changed (empty diff)."
---

## Launch prompt
You carry out Q13, a read-only review of the whole plan on the integration
branch. Read DISCOVERY.md and HANDOFF.md of the plan first (decisions DQ1 to
DQ9, Principle, and every task entry), then the points below.
Change no file. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, the verdict per point
with its evidence, and the entries to add to the plan's HANDOFF.

## Useful context
- The total diff: `git diff main...plan/qa14707`.
- `phases/QA14707/README.md`, "Critères d'acceptation globaux".
- The task files of the plan and their reports in the plan's HANDOFF.

## Implementation notes
Points to check:
1. **Principle.** The total diff adds no new regex or word list to understand language. Each removed rule (Q09, Q10, Q11) is really gone: `git grep … -- agents libs`. `plans/` and `phases/` still quote the names, legitimately.
2. **Budget.**
   - `MAX_LLM_CALLS_PER_TURN` is unchanged.
   - A clarification turn no longer makes a synthesis call.
   - There is no new LLM call anywhere else.
3. **Frozen contracts.**
   - `GUARD_SCORE_NAMES` and `FALLBACK_SCORE_NAMES` have lost no name.
   - `contracts/geo_intent.schema.json` is identical to the model, and has no `ambiguity.options` (DQ5).
   - `contracts/mcp_b2c_tools.json` was not touched.
4. **R9.** `generate_booking_link` stays uncallable without a confirmation, and without a pending offer or a list on screen.
5. **GDPR.**
   - The triage receives the pending question, never the profile.
   - No message content goes into the metrics: the existing test is green, and the new discarded-`mention` counter carries no text.
   - No file of `baseline/` is in the diff.
6. **Cases to keep.** Each of these has a green test: "Gare du Nord" without a city, gare de Lyon (through `ambiguity.reason`, DQ6), Budapest, La Défense, "near 11580", Saint-Paul, Manhattan.
7. **Eval harness (DQ4).** Multi-turn items are replayed turn by turn on one session, and the trace facts are scoped to the last turn (offline tests).
8. **Truth of the documents.** HANDOFF, CHANTIERS, the S-L plan, the code comments and the plan's own DISCOVERY / HANDOFF say what the code does.
9. **Geo decisions.**
   - DQ6: gare de Lyon goes through `ambiguity.reason`.
   - DQ7: `select_us_postal_anchor` is gone.
   - DQ8: no `country` filter without a named country; the guess only breaks ties.
   - DQ9: Q08's tests rest on H5's recorded fixtures, not on a fabricated shape.
10. **Gates.** The 4 commands are green, the +400-day calendar guard included.

## Out of scope
Any change to a file.
