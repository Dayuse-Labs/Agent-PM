# HANDOFF — qa14707
Entries: `deviation`, `blind-spot`, `decision`, `debt`, `needs-human`, `ticket`, `review`, rated `minor` or `major`.

## source plan

- decision · major · DQ1 (D-Q1 in `phases/QA14707/README.md`). The current search leaf produces the `GeoIntent` first, as a structured argument of `geocode_location`, in place of the `city` / `zone` / `raw_user_message` strings. There is no dedicated leaf, no 4th LLM call, and no need for decision D-1 of the S-L plan. The contract and its mapping to geocoding are those of the S-L plan (§3), plus `postal_code`. S-L3 and S-L4 (the dedicated leaf) would later only move where the object is **produced**, and only if replays show gpt-4o-mini can't hold the schema in the leaf. Only the sequence of L1 changes, not the target. (settled by the user, 2026-10-14)
- decision · major · DQ2 (D-Q2). A clarification question (missing city, homonym) is **rendered by template in the concierge, without going through the synthesis**. The tone is less polished, but no invented option is possible, and the turn costs one LLM call fewer. (settled by the user, 2026-10-14)
- decision · major · DQ3 (D-Q3). **Deploy `main` now** (#135: criteria resumed after a question, named hotel, guard #18), as soon as the reference replay H1 shows no regression. QA is testing a build that lacks the fixes of 09/30. The regex `fc5cbd9` is accepted as a transition and removed in Q09. This is a human action (H2), and it can only follow phase 1, because H1 needs Q01. (settled by the user, 2026-10-14)
- decision · major · DQ4. Q01 extends `evals/langfuse_experiment.py` in two ways:
  - It replays every user turn of `input.messages`, in order and on one session, and evaluates the last reply. Until now it posted only the last user message, after priming `input.profile`.
  - It extracts from the trace the result of `geocode_location` and the inline tool calls of the concierge (`generate_booking_link`, `find_hotel_by_name`), scoped to the last turn.

  The existing multi-turn sets (`b2c-dialogue-state`…) become truly multi-turn, and H1 sets the new reference. Priming the state per case was rejected: the slot names differ between `cbe88b9`/`main` and the code after Q04, so H1 and H3 would not be comparable. (settled by the user, 2026-10-14)
- decision · major · DQ5. `GeoIntent` v1.1 keeps `ambiguity: null | {reason ∈ homonym | city_needed | too_vague}` and **drops `ambiguity.options`**. No option of a question is ever written by an LLM: options come only from the geocoder, through `Clarification` (Q03). This is a deviation from §3 of the S-L plan, recorded by Q12. (settled by the user, 2026-10-14)
- decision · major · DQ6. The S5 rule stays (PR #91, HANDOFF 2026-08-26): a place named after a city it is not in ("gare de Lyon", a Paris station) still makes the code ask for the city. In the `GeoIntent` it becomes a field rule:
  - The LLM sets `ambiguity.reason = "city_needed"` and gives no city.
  - The code maps that to `geocode_city_needed`.

  Q07 removes the "leave `city` blank" wording of the prompt, not the rule. Q07 maps only `city_needed`. `homonym` and `too_vague` are read and logged, and the geocoder keeps deciding homonyms. (settled by the user, 2026-10-14)
- decision · major · DQ7. Q10 removes `select_us_postal_anchor`, which `phases/SL7-retraits-regles-langage.md:26` lists as S-L7f, marked "décision de Fabien avant tout retrait". This is that decision. The source plan's claim that S-L7 had "forgotten" this rule is wrong. The "near 11580" tests stay the specification. (settled by the user, 2026-10-14)
- decision · major · DQ8. When the user names no country, the country of a postcode or an address with a postcode is decided as follows:
  - Only a **named** country (`country_named`) is a hard Mapbox filter.
  - Otherwise geocoding searches everywhere, and only the candidates whose `context.postcode` equals the extracted `postal_code` are kept.
  - Among those, the LLM's guess (`places[].country`) breaks ties first, then the market's country.

  The guess stays a soft hint, never a filter, in line with the leaf's doctrine (`agent.py:191-198`). The source plan's rule ("the guess as a filter") is replaced: 75009 is also a US ZIP (Celina, TX), and Raphael's sessions run on the en/USD market. (settled by the user, 2026-10-14)
- decision · major · DQ9. Q08's Mapbox v6 fixtures are real responses recorded by Fabien (H5) before phase 3, never synthetic, because the postcode check relies on the real shape of `context.postcode` / `context.place`. (settled by the user, 2026-10-14)
- decision · minor · Conversion changes:
  - Q11 depends on Q09. Q09 deletes the leaf's writer of `pending_place` (`geocode_tool.py:771` → `response_bridge.py:1637-1638`), and Q11 removes the concierge's field (`profile.py:280/343/773`, `agent.py:1714-1715`).
  - Q02 covers 4 call sites: the source plan had missed `ui/messages.js:757-758`.
  - Q07 keeps the current core of `geocode_location` as an internal function, and the tool becomes a mapping wrapper (size).
  - Q09 owns `response_bridge.py`.
  - Q04 owns the seam test and the HTTP SSE test.
  - Q12 owns the phase files `SL2`, `SL5` and `SL7`.
- decision · major · Principle (README of the source plan, non-negotiable):
  - The LLM understands within a closed schema. The code owns the values and checks them against the provider's facts (Mapbox, inventory).
  - **No new regex or word list to understand language.** The existing rules are removed one by one in phase 4 (decision L3), each covered by a test and an eval case.
  - **No new LLM call per turn.** `MAX_LLM_CALLS_PER_TURN = 3` (`agents/b2c_concierge/b2c_concierge/budget.py:18`) is unchanged, and a clarification turn makes one call fewer.
  - `GUARD_SCORE_NAMES` and `FALLBACK_SCORE_NAMES` (`libs/b2c_common/b2c_common/scores.py`) lose no name. A guard whose measure changes keeps its name.
- decision · major · #134. Decided on 2026-10-12: #134 (Victor) is ported to `main` by families, and the geo family comes after L1. #134 has its own `pending_clarification`, `pending_location`, and a `location_intent` in the triage. This plan **fixes the model** of the clarification and of the place (`Clarification`, `pending_clarification`, `GeoIntent`). The port of #134's geo family must conform to it, not the reverse.
- needs-human · major · H2 (source plan). **Deploy `main`** on Railway following `DEPLOY.md` (DQ3), once H1 shows no regression. Stamp `LANGFUSE_RELEASE` before `railway up`, then check the release in a trace. This blocks no task: agents never deploy (`railway *` is denied).
- needs-human · major · H4 (source plan). After the plan is merged: final deployment, retest by Raphael, then a point-by-point answer on dayuse-com#14707 (build, proof, what remains).
- ticket · minor · Ask Raphael which URL and market he tested. All his traces carry `locale:"en"` and `currency:"USD"`, so the geocoder's question comes out in English and only the synthesis turns it back into French. This blocks no task.

## Q02

- deviation · minor · Q02: the slot formatter `formatSlotTime` / `formatSlotRange` lives in its own DOM-free module `web/vendor/static/js/chat/slot_time.js` instead of `utils.js`, so bare node can load it (`utils.js` imports `state.js`, which touches the DOM at import). This is what the task's implementation notes asked for, it stays inside the owned `chat/**` path, and it changes no contract.
- decision · minor · Q02: `formatSlotTime` handles zh-HK and zh-SG (`10:00`), but `getLanguage()` never returns them. `i18n.js:6` limits SUPPORTED_LANGUAGES to en/fr/es/it/pt/de/nl, and `normalizeLanguage` (`i18n.js:8-14`) maps zh-HK to `en`. In the widget the zh branch is therefore dead today: a zh-HK conversation gets an English UI and an English slot (`10am`), which is at least consistent with the rest of the widget. Adding Chinese to the widget is a product choice outside this plan (UX2 set seven languages). The branch matches the site's rule and is unit-tested.
- blind-spot · minor · Q02: pytest was not run in the task worktree because it has no `.venv`, so the pytest run of the new widget suite is unverified there. Coverage itself is not at risk. `tests/test_market_table_drift.py:302` globs `tests/widget/*.test.mjs`, so it picks up `widget_slot_time.test.mjs` automatically. Every later task's `.venv/bin/pytest -q` verification on `plan/qa14707` (Q01, Q03 onward, Q13) runs that suite from the main checkout's working venv (E2). Nothing is needed beyond the existing verifications.
- rejection · minor · attempt 1, evaluation: Negative control (DoD criterion 3) is not met as written. The criterion asks the report for the command that was run and its failing output, showing that the `fr` case of tests/widget/widget_slot_time.test.mjs fails against the output of the OLD `formatTimeAMPM`. The report gives no command. It also says the worker did not run the old `formatTimeAMPM` against the test: it forced the English branch of the new `formatSlotTime` instead. To close the gap, extract the deleted `formatTimeAMPM` with `git show plan/qa14707:web/vendor/static/js/chat/utils.js`, or copy the function into a scratch module so the DOM-touching state.js import is not needed. Then run the `fr` assertions (`10h – 16h`, `10h30`) against it with `node --test` and quote the exact command and its failing output (expected `'10h – 16h'`, actual `'10am – 4pm'`) in the report.
