---
id: Q02
title: Time slot in the language of the conversation
phase: 1
model: sonnet
model_reason: "Source plan's model, kept: a fix bounded to the widget, and the rule to reproduce is given."
effort: low
depends_on: []
parallel_batch: 1B
owned_files:
  - web/vendor/static/js/chat/**
  - tests/widget/**
resources: []
prerequisites: [E1, E2]
context_budget: 20%
token_estimate: 0.8M
max_turns: 30
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "node --test 'tests/widget/*.test.mjs'"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "`tests/widget/widget_slot_time.test.mjs` covers `fr` (`10h – 16h`, `10h30`), `en` (`10am – 4pm`, `4:30pm`), `zh-HK` (`10:00`) and one other language of the widget."
  - "The list card (`hotels/card.js`) and the booking card (`ui/messages.js`, both raw-slot sites `:663` and `:757`) go through the same formatter (visible in the diff)."
  - "Negative control, as report evidence (the command run and its failing output): the `fr` case of the new test fails against the output of the old `formatTimeAMPM`."
  - "`git grep formatTimeAMPM -- web tests` returns nothing."
---

## Launch prompt
You carry out Q02 on the branch task/Q02. Read DISCOVERY.md first,
then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- **Raphael's report 1.** His screenshot shows a French conversation with the card "B&B HOTEL Lyon Nord" and the pill `10am - 4pm`. Raphael writes "cut-off", but he does mean the time slot: Fabien confirmed it on 2026-10-14.
- **`web/vendor/static/js/chat/utils.js:46`**: `formatTimeAMPM` hard-codes am/pm and takes no language. It is called at `hotels/card.js:677-678` and `:717-718`.
- **`web/vendor/static/js/chat/ui/messages.js`** shows the raw slot `${start_time} – ${end_time}` at `:663-664` and at `:757-758`. That is a third format, and there are two sites.
- **`formatRating`** in `utils.js` already formats according to the language of the **conversation** (S-CX8). Follow the same model: `getLanguage()` from `i18n.js`.
- **The site's rule**, to reproduce as is (`~/PhpstormProjects/dayuse-com/apps/frontend/web/utils/formatTime.ts`):
  - `en` → `11am`, `5pm`, `11:30am`;
  - `zh-HK` and `zh-SG` → `11:00`;
  - all other languages → `11h`, `11h30`.
- **Tests**: the `node:test` suites of `tests/widget/` are also run by pytest (`tests/test_market_table_drift.py:284-313`, on every `tests/widget/*.test.mjs`).

## Implementation notes
- Write a single formatter, for example `formatSlotTime(hhmm, lang)`, computed from `HH:MM`. Don't `replace` on an Intl string: the hours already arrive as `HH:MM`.
- Put it in a module without DOM. `utils.js` imports `state.js`, which calls `document.querySelector` at import, so a bare-node test of `utils.js` would need stubs (DISCOVERY, Pitfalls). The call sites pass `getLanguage()`.
- It replaces `formatTimeAMPM` and the raw slots at all 4 call sites. Delete `formatTimeAMPM` once it has no caller left.
- Don't touch `libs/b2c_common/b2c_common/search_page.py:48` (`6am`): it is the site's URL format, not a display.

## Out of scope
Any backend change.
