# DISCOVERY — qa14707

## Existing context

- **Goal** (`phases/QA14707/README.md`): Raphael's three QA reports on dayuse-com#14707 (2026-10-14) never come back, in any variant.
  1. A card's time slot is shown in the language of the conversation.
  2. A city, an address or a postcode written in the message never triggers a question about the city.
  3. When a question is legitimate, a single answer launches the search with the original date and time slot. The same question is never asked twice, and no option is invented.
- **Evidence and root causes**: `phases/QA14707/DIAGNOSTIC.md` (14 Langfuse traces, release `cbe88b9`). The line numbers of the source tasks are those of `2bac3eb`. `main` `c76f0a2` has the same code, because only docs were merged since.
- **Production is not `main`** (HANDOFF.md, 2026-10-14):
  - prod serves `cbe88b9`, and #135 is not deployed;
  - `main` is 42 commits ahead.
- **Invariants** (CLAUDE.md):
  - LiteLLM only;
  - A2A between the concierge and the leaves;
  - leaves are stateless, and Redis belongs to the concierge;
  - ≤ 3 LLM calls per turn, enforced in code (`budget.py:18`);
  - `GUARD_SCORE_NAMES` / `FALLBACK_SCORE_NAMES` are frozen;
  - `baseline/` is never committed.
- **There is no CI** (CHANTIERS.md §1): GitHub Actions is dead. The local gates are the only gate.
- **Related plan**: `reports/PLAN-LEAF-GEO-2026-10-08.md` (S-L), whose §3 holds the `GeoIntent` v1 contract and its mapping to `geocode_location`. `evals/PRESERVATION.md` lists the geo cases to keep.
- No `AGENTS.md`, no `.claude/rules/`, no project skills.

## Verified commands

Run on `main` `c76f0a2`, 2026-10-14. **No failure was already present**, so none counts against the tasks.

| Command | Result |
|---|---|
| `/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q` | 2416 passed, 1 skipped, 27 s |
| `/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check .` | All checks passed |
| `/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs` | Success, 66 source files (`evals/` and `scripts/` are not typechecked) |
| `bash scripts/dayuse_guardrails.sh .` | OK (it greps `*.py` only) |
| `node --test 'tests/widget/*.test.mjs'` | 16 pass |
| `/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/python scripts/langfuse_seed_datasets.py --dry-run` | "validated 77 items across 6 file(s)", offline |

Notes on these commands:

- **pytest**
  - It includes `tests/test_calendar_rot.py` (about 12 s), which replays the whole suite with the clock shifted by +400 days.
  - It also runs the widget suite: `tests/test_market_table_drift.py:284-313` calls `node --test` on every `tests/widget/*.test.mjs`.
- ⚠️ **`node --test tests/widget/` (a directory) FAILS** on node 24 ("test at tests/widget:1:1 … failed"). Pass the glob.
- **`--dry-run`** checks only that `id`, `input`, `expected_output` and `metadata` are present, that `input.messages` is not empty, and that ids are unique. `--only <stem>` fails if the stem is not in `DATASET_NAMES`.
- **`evals/langfuse_experiment.py` is live only**: it needs the concierge on :8100, a real Redis and Langfuse keys. It is never a verification. The live replays are H1 and H3, done by Fabien.
- **Tests are offline**:
  - Redis is fakeredis: the autouse `ProfileStore` in `agents/b2c_concierge/tests/conftest.py`, and `tests/api/conftest.py`.
  - No port, no database, no shared service, so no task declares a resource.

## Quick map

**Search leaf** (`agents/hotel_search_agent/hotel_search_agent/`)

| File | What is there |
|---|---|
| `agent.py` | The prompt's location section is at `:162-202`. The S5 exception ("NAMED AFTER A CITY THEY ARE NOT IN") is at `:173-183`, and "leave `city` blank" at `:189-190`. |
| `geocode_tool.py` | Holds `geocode_location`:<ul><li>signature at `:386`;</li><li>`fc5cbd9` (`_city_named_in_message`, `_CITY_AFTER_PREPOSITION_RE`) at `:230-270`;</li><li>`geocode_city_needed` at `:595-610`. It is the `mark_level` status of a `geocode_ambiguous` error (`:596-599`), not an error code of its own;</li><li>US ZIP forcing at `:671-675`;</li><li>homonym at `:750-780` and `:910`; the leaf writes `pending_place` at `:771`;</li><li>`_complete_pending_place` at `:944-968`;</li><li>carry-over from `profile_in`: the before-tool callback `inject_profile_geo_context` (`:971-1028`), which works on the flat `city`/`zone` keys (fill at `:1003-1009`).</li></ul><br>`scripts/probe_geo_landmarks.py:204` calls `geocode_location(**args)`. |
| `geo_resolver.py` | `city_needed_question` (`:247`), `_CLARIFY_MANY`, homonyms (`:486-525`), the inventory tier (`:58`). |
| `geo_guards.py` | `select_us_postal_anchor` (`:458`), and `STREET_SUFFIX_TOKENS` within `:417-514`. |
| `mapbox_client.py` | Geocoding v6 (`GEOCODE_URL` `:29`). It reads `context.country` and `context.region` (`:229-264`). |
| `response_bridge.py`, `contract.py` | The leaf's DataPart. `search_context` is the model for passing structured facts to the concierge. `response_bridge.py:1637-1638` relays `pending_place` into `profile_delta`. |

**Concierge** (`agents/b2c_concierge/b2c_concierge/`)

| File | What is there |
|---|---|
| `agent.py` | <ul><li>`_attach_outgoing_datapart` at `:365`. It puts `context_text` (EARLIER REQUEST / YOU ASKED / REPLY) **before** the user's words (`:380-386`), so the leaf reads them as one message;</li><li>`_SYNTHESIS_INSTRUCTION` at `:451`, and the synthesis call at `:691`;</li><li>anti-loop at `:900-928`;</li><li>a fast path that uses `is_bare_affirmative` at `:1200-1212` (`answers_pending` at `:1206`);</li><li>triage call at `:1226`;</li><li>routing priority at `:1328-1362` (ack + pending → search at `:1352-1359`);</li><li>`pending_search_context` call at `:1645`;</li><li>clearing of `pending_place` at `:1714-1715`;</li><li>other `is_bare_affirmative` uses, outside the clarification route: the greeting relaunch (`:1160`) and `search_exhausted` (`:1505`).</li></ul> |
| `profile.py` | <ul><li>`_AFFIRMATIVE_RE` at `:136` and `is_bare_affirmative` at `:143`;</li><li>`pending_place` is an ordinary profile field (`:280`, `:343`, `:773`), **not** in `_CONCIERGE_ONLY_KEYS` (`:365-381`);</li><li>`next_pending_search` at `:985`;</li><li>`pending_search_context` at `:1002`;</li><li>`extract_final_question` at `:1063`;</li><li>`questions_equivalent` at `:1077`.</li></ul> |
| `triage.py` | <ul><li>`Triage` at `:149`;</li><li>`answer_to`, checked at `:268-278`;</li><li>examples from `:392` on;</li><li>`previous_question` / LAST ASSISTANT QUESTION at `:487-519`.</li></ul> |
| `templates.py` | `TEMPLATE_LANGUAGES` (7 languages), `_NEEDS_SELECTION_NO_LIST` (`:364-367`). |
| `inline_tools.py` | `_extract_hotel_name_candidate` (`:146`). The inline MCP calls are TOOL observations named `mcp-<tool>` (`:106`): `mcp-generate_booking_link`, `mcp-find_hotel_by_name`. The guardrail spans are `resolve-named-hotel` (`:161`) and `authorize-booking-link` (`:1132`). |
| `budget.py:18` | `MAX_LLM_CALLS_PER_TURN = 3`. |

**Shared and contracts**

- `libs/b2c_common/b2c_common/`: `scores.py` (frozen names), `timeslot.py`. Its tests are in `libs/b2c_common/tests/`. Its `pyproject.toml` declares only `starlette`; pydantic comes in with ADK, and Q06 declares it.
- `contracts/mcp_b2c_tools.json`: only `scripts/refresh_mcp_contract.py` writes it, and a human runs that script.
- `tests/test_mcp_contract.py` replays the real before-tool chain on the `search_offers` / `find_hotel_by_name` arguments.
- `tests/test_leaf_concierge_seam.py` locks the leaf → concierge seam (S-G10). `tests/api/test_facade_http.py` holds the real HTTP and SSE tests (`/v3/chat/stream`).

**Widget** (`web/vendor/static/js/chat/`)

- `utils.js:46` `formatTimeAMPM` is called at `hotels/card.js:677-678` and `:717-718`.
- `ui/messages.js` shows raw slots at `:663-664` **and** `:757-758`.
- `i18n.js` holds `getLanguage()`. `formatRating` in `utils.js` already follows the conversation language.

**Evals**

- `evals/datasets/*.jsonl` and their `README.md`: the assertion vocabulary, and `metadata.status` = `target` | `regression_guard`.
- `evals/langfuse_evaluators.py`: `_RESPONSE_CHECKS` `:392-411`, `_TRACE_CHECKS` `:487-492`, `ALL_EVALUATORS` `:508`.
- `evals/langfuse_experiment.py`:
  - `_last_user_message` (`:77`);
  - `_derive_route` (`:128`), whose route is derived from the triage family;
  - trace facts (`:146-226`): only `search_offers_args`, `pick`, `family`, `route`. The harness reads every trace of the session (`:165-176`). The leaf's tools are ADK `execute_tool` spans, a TOOL observation named after the tool, as already used for `search_offers` (`:177`);
  - `task` (`:234`).
- `scripts/langfuse_seed_datasets.py`: `DATASET_NAMES` `:35-42`.

## Observed conventions

- Structured facts from the leaf to the concierge travel in the leaf's DataPart, by the same channel as `search_context`, never in text.
- Code templates exist in 7 languages (`TEMPLATE_LANGUAGES`). A template that asks a question also sets `profile.last_clarifying_question` (`agent.py:1468`, `:1580`, `:1599`).
- `libs/b2c_common/b2c_common/__init__.py` re-exports only part of the package. New modules are imported as submodules (`from b2c_common.clarification import …`). Q03 and Q06 run in parallel, so neither touches `__init__.py`.
- Dates in tests are relative to the clock, following the idiom of the function under test. A hard-coded date makes `tests/test_calendar_rot.py` fail.
- Every new model environment variable is neutralized in the root `conftest.py`, because `import litellm` loads the local `.env`.
- An `expected_output` key with no evaluator silently scores nothing.
- Metrics carry zero message content, and a test locks this. A counter of discarded `mention`s carries no text.
- **A plan task is not a session.** CLAUDE.md's "Fin de session" (update `HANDOFF.md`, commit + MR) applies to the plan as a whole. Only Q12 touches the repository's `HANDOFF.md`, and no task opens a PR or pushes. Each task reports in its own report, and the scribe writes the plan's HANDOFF.
- `git grep` checks of a removal carry a path filter (`-- agents libs`, `-- web tests`). `plans/` and `phases/` quote the removed names, and the tasks don't own them.

## Pitfalls and fixes

- **Worktrees**
  - There is no `.venv` in a worktree. Use `/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/{pytest,ruff,mypy,python}`.
  - `pytest.ini` (`pythonpath`, `--import-mode=importlib`) and `mypy.ini` (`mypy_path`) put the worktree's sources first.
  - The venv's editable `b2c_common` points at the main checkout. So if a new `b2c_common` module is not found in a worktree, the main checkout's copy is being imported.
  - `.env` is copied into the worktrees (`.worktreeinclude`). Never read it.
- **Widget**: `utils.js` imports `state.js`, which calls `document.querySelector` at import (`state.js:7-9`, `:42-44`). A bare-node test of `utils.js` or `card.js` needs `document`/`window` stubs. A pure formatter in a DOM-free module avoids that.
- **ADK**
  - A tool parameter without a default is rejected before the function runs, and it reads like model non-determinism.
  - ADK 2.4 builds the declaration of a pydantic parameter (`.venv/lib/python3.12/site-packages/google/adk/tools/_function_parameter_parse_util.py:169-178`) and converts the argument back with `model_validate` (`google/adk/tools/function_tool.py:173-182`).
  - The pydantic field descriptions end up in the tool declaration the LLM reads.
- **Mapbox**: Search Box without `proximity` is biased by the caller's IP, so A/B replays must share one IP.
- **The LLM copies a sentence shown to it**, even when told not to. Imposed text is deduplicated in code, or never goes through the LLM (DQ2).
- **`evals/langfuse_experiment.py`**:
  - It used to post only the last user message (fixed by Q01, DQ4).
  - There is one trace per turn across A2A (OBS4). With multi-turn replay, facts must be scoped to the last turn.
  - `_derive_route` deduces the route from the triage family, and that becomes wrong after Q05. Assert on tool facts instead.
- **Shell**: in the user's shell, `cat` is an alias for `bat`, so use `command cat` or Read. Watch zsh's `$S:t` and `echo =====` (HANDOFF PORT1).
- **Data never touched, read or committed**: `.env`, `baseline/`, `dayuse_eval_pack/data/`, `.run-logs/`, `evals/reports/`. The eval cases are synthetic, or Raphael's test sentences.

## Context recommendations (end of run)
