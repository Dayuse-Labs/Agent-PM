---
id: Q04
title: "Concierge: clarification rendered by template, persistent state, anti-loop on the state"
phase: 2
model: opus
model_reason: "Source plan's model, kept: touches the core of the concierge (`agent.py`, `profile.py`), the synthesis and a guard."
effort: high
depends_on: [Q03]
parallel_batch: 2B
owned_files:
  - agents/b2c_concierge/b2c_concierge/agent.py
  - agents/b2c_concierge/b2c_concierge/profile.py
  - agents/b2c_concierge/b2c_concierge/templates.py
  - agents/b2c_concierge/tests/**
  - tests/test_leaf_concierge_seam.py
  - tests/api/test_facade_http.py
resources: []
prerequisites: [E2]
context_budget: 45%
token_estimate: 4.7M
max_turns: 80
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/b2c_concierge/tests"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Test: a turn where the leaf sends up a `Clarification` makes **no** synthesis call. Its reply is the template in the language of the conversation, for at least `fr` and `en`."
  - "Test: the next turn sends the leaf the original request (\"… demain à 14h\") and the structured clarification; the time slot and the date are in it."
  - "Test: the same clarification on two turns in a row gives two different texts, and on the third there is no question any more."
  - "Test: no option absent from the `Clarification` appears in the reply (rendering without LLM)."
  - "Test in `tests/api/test_facade_http.py`: on the SSE path (`/v3/chat/stream`), a clarification turn still emits `progress` and then the template's text."
  - "Seam test in `tests/test_leaf_concierge_seam.py`: the `Clarification` emitted by the leaf (Q03) goes through the encoded and then decoded DataPart and comes out as the concierge's template. This guards against a placement bug that each side's unit tests would miss (S-G9)."
  - "Negative control, as report evidence (the command run and its failing output): without the fix, the \"no synthesis call\" test fails."
  - "`GUARD_SCORE_NAMES` is unchanged: `anti_clarification_loop` keeps its name."
  - "Test: a `city_needed` `Clarification` (`options=[]`) renders a reply that names its `subject` and offers no numbered option, in `fr` and `en`."
  - "Test: a `homonym` `Clarification` with 2 options renders exactly those 2 labels, numbered in the order of the object, and no other option line."
---

## Launch prompt
You carry out Q04 on the branch task/Q04. Read DISCOVERY.md and HANDOFF.md
of the plan first (decisions DQ2, #134), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- `phases/QA14707/DIAGNOSTIC.md` §1, reports 2 and 3. Decision **DQ2**: the clarification question is rendered by template, without synthesis.
- **The `Clarification` model** from Q03: `libs/b2c_common/b2c_common/clarification.py`. The leaf sends it in its DataPart, like `search_context`.
- **Current state on `main` (#135)**:
  - `profile.pending_search = {request, question}` is set by `next_pending_search` (`profile.py:985`).
  - The `question` is extracted **by regex** from the synthesis's paraphrase: `extract_final_question` (`profile.py:1063`), called at `agent.py:904`, `:920` and `:926`.
  - The same extraction feeds `profile.last_clarifying_question` (`agent.py:928`). Elsewhere, code templates already set that slot directly (`agent.py:1468`, `:1580`, `:1599`): that is the model to follow.
  - `pending_search_context` (`profile.py:1002`, called at `agent.py:1645`) builds the context "EARLIER REQUEST / YOU ASKED / REPLY", and `_attach_outgoing_datapart` (`agent.py:365`) attaches it.
- **Synthesis**: `_SYNTHESIS_INSTRUCTION` (`agent.py:451`), called at `:691`.
- **Anti-loop guard**: `agent.py:900-928` (`questions_equivalent`, `profile.py:1077`). It compares paraphrases, and it did not fire on trace C1.
- **Templates** exist in 7 languages: `templates.py` (`TEMPLATE_LANGUAGES`).

## Implementation notes
1. **Rendering.** When the leaf sends up a `Clarification`, the reply is the concierge's template, in the language of the conversation, built from the object (`subject`, numbered options).
   - No synthesis call happens on that turn, and the turn's LLM budget reflects it.
   - Check that the SSE path (`/v3/chat/stream`) emits `progress` and then the text when the synthesis is skipped, as for the existing templates.
2. **State.** Add a new slot owned by the concierge: `profile.pending_clarification = {clarification, request}`.
   - `request` is the request not yet searched, accumulated like `pending_search` (500 chars max).
   - The rendered template also sets `profile.last_clarifying_question`, like the other code templates. The triage receives that text, written by the code, on the next turn (`previous_question`, Q05).
   - The next turn sends the leaf three things: the original request, the **structured** clarification (not a paraphrase), and the answer. The leaf re-extracts the date, slot and budget from the original request: it understands, without regex.
   - On this path, `pending_clarification` replaces the pair `pending_search.question` + regex. The leaf's free questions stay on `pending_search`; their regex is removed in Q11.
3. **Anti-loop on the state.**
   - If the same `Clarification` (same `kind`, same `subject`) comes back on the next turn, the template switches to a different variant: the geocoder's options numbered or, without options, "I can't find « X » without the city" with an example answer.
   - A third time, no question: an honest reply that offers to search by city.
   - The guard keeps its name `anti_clarification_loop` (`GUARD_SCORE_NAMES` is frozen); only its measure changes (state instead of text).
4. ⚠️ #134 (Victor) also has a `pending_clarification`. This model is authoritative (HANDOFF, decision #134), and the name is kept so that the port of #134 plugs into it.

## Out of scope
- The triage and the routing priority (Q05).
- Removing the regex of the free questions (Q11).
