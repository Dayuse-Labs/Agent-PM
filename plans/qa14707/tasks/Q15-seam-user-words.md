---
id: Q15
title: "Seam: the leaf reads the user's own words apart from the concierge's context"
phase: 3
model: sonnet
model_reason: "A bounded seam test over code Q04 and Q07 already delivered; no production change."
effort: medium
depends_on: [Q07]
parallel_batch: 3B
owned_files:
  - tests/test_leaf_concierge_seam.py
resources: []
prerequisites: [E2]
context_budget: 25%
token_estimate: 0.8M
max_turns: 30
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q tests/test_leaf_concierge_seam.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Test: on a turn that answers a pending homonym `Clarification` (two options, `Manhattan (New York, US)` and `Manhattan (Kansas, US)`), the message the concierge builds with `_attach_outgoing_datapart` and the context text from `pending_clarification_context` holds that context as its own text part, placed before the user's words. On that message, the leaf's `response_bridge.read_user_words` returns exactly the user's reply (« New York »), and `response_bridge.read_input_text` contains both the EARLIER REQUEST and the reply."
  - "Test (Mapbox mocked, `geocode_tool.geocode_core` patched to capture its arguments): the same message, run through the leaf's real `geocode_location` FunctionTool, passes `geocode_core` a `raw_user_message` equal to the user's reply, with no option label and no text of the YOU ASKED JSON in it."
  - "Negative control: the report quotes the exact command and the failing output of the first test after a scratch change that joins the context into the user's text part. The scratch change is not committed."
  - "The diff touches only `tests/test_leaf_concierge_seam.py`; the existing seam tests keep their assertions."
---

## Launch prompt
You carry out Q15 on the branch task/Q15. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle, the Q04 and Q07 entries), then the files listed
in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- **Concierge side.** `_attach_outgoing_datapart` (`agents/b2c_concierge/b2c_concierge/agent.py`, search `def _attach_outgoing_datapart`) puts `context_text` as its own `Part` BEFORE the user's parts, then the DataPart. On a clarification answer, the context text comes from `pending_clarification_context` (`agents/b2c_concierge/b2c_concierge/profile.py`), which embeds the `Clarification` as JSON under YOU ASKED.
- **Leaf side.** `read_input_text` and `read_user_words` (`agents/hotel_search_agent/hotel_search_agent/response_bridge.py`). `geocode_location` (`agents/hotel_search_agent/hotel_search_agent/geocode_tool.py`) checks mentions against `read_input_text` and sets `raw_user_message = read_user_words(tool_context)` before calling `geocode_core`.
- **Why it matters** (Q07 HANDOFF entry): the YOU ASKED JSON lists every option of a homonym question. Fed to the core, it would make `_complete_pending_place` decide nothing and could let the text state tier pick another option's state.
- **Existing helpers** in `tests/test_leaf_concierge_seam.py`: `_over_the_wire`, `_concierge_answer`, `_LeafCtx`, `TestClarificationSeam`. Reuse them.

## Implementation notes
1. Build the concierge's real outgoing message (no hand-written parts list), then convert it as the leaf receives it, as the existing seam tests do.
2. Capture what `geocode_core` receives by monkeypatching the module attribute `geocode_tool.geocode_core`. Mock Mapbox; no network, no `.env`.
3. No production change. If the seam does not hold, finish `blocked` with the failing output.

## Out of scope
- Changing how the concierge builds YOU ASKED (Q11).
- Removing `_complete_pending_place` (Q09).
