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
- **Widget tests**: `web/vendor/static/js/chat/slot_time.js` has no imports and can be tested in bare node. Pytest runs the widget tests through `tests/test_market_table_drift.py`, so a new `.test.mjs` is picked up with no config change.
- **Negative-control recipe** (widget): `git show plan/qa14707:web/vendor/static/js/chat/utils.js | sed -n 46,58p` extracts the old `formatTimeAMPM`. Re-export it under the new names in a scratch module, sed the test's CHAT URL to the scratch dir, then run `node --test --test-name-pattern='^fr' <copy>`. This avoids importing `utils.js`, which touches the DOM through `state.js`.
- **Worktree b2c_common checks**: in the worktree, b2c_common tests and mypy pick up the worktree's geo_intent.py through pytest.ini and mypy.ini. jsonschema is available in the venv (pulled in by litellm) and is already used by tests/test_mcp_contract.py.
- **Isolation guard**: heredocs with chaining are refused (this includes `cat >> file <<EOF` chained with pytest), so write files with the Write tool and extend them with Edit. A negative-control scratch edit of a production file is reverted by editing it back; nothing needs stashing or resetting.
- **`--dry-run`** checks only that `id`, `input`, `expected_output` and `metadata` are present, that `input.messages` is not empty, and that ids are unique. `--only <stem>` fails if the stem is not in `DATASET_NAMES`.
- **`evals/langfuse_experiment.py` is live only**: it needs the concierge on :8100, a real Redis and Langfuse keys. It is never a verification. The live replays are H1 and H3, done by Fabien.
- **Tests are offline**:
  - Redis is fakeredis: the autouse `ProfileStore` in `agents/b2c_concierge/tests/conftest.py`, and `tests/api/conftest.py`.
  - No port, no database, no shared service, so no task declares a resource.
- From a worktree, the 5 verifications run with `/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/{pytest,python,ruff,mypy}` and `bash scripts/dayuse_guardrails.sh .`. `evals/` is not typechecked by mypy (66 files), but ruff covers it.
- Q07 final commit da7f1a7 on task/Q07: `pytest -q` 2716 passed, 1 skipped (25 s); leaf tests + test_mcp_contract.py 710 passed; ruff all checks passed; `mypy agents libs` no issues in 68 files; dayuse_guardrails OK. No negative-control rerun for the older criteria. The two new tests were run red against the old mapping (city '' and zone None), then green after the fix.
- Q08 final commit 9bcd21f: `/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q` gives 2758 passed, 1 skipped (17 s); `pytest -q agents/hotel_search_agent/tests` gives 743 passed. Just before the commits: `ruff check .` passed, `mypy agents libs` no issues in 68 files, `bash scripts/dayuse_guardrails.sh .` OK.
- Q24: `pytest -q evals/tests` gives 205 passed, 1 skipped. `ruff check .` passes. Earlier: `pytest -q` 2843 passed, 1 skipped; `dayuse_guardrails.sh .` OK; seed dry-run validated 88 items across 7 files.
- Q17 evidence: before the first fix, the new tests on the parent commit gave 11 failed and 1 passed. On the Versailles case the core spy saw `{'city': '', 'country_code': None, ...}` and zone None, and ADK logged 'Failed to convert argument intent ... city Input should be a valid dictionary or instance of CityRef'. After the second fix, the 2 new non-string-kind cases raise TypeError against the previous source and pass with the fix (65/65 in test_geo_intent_mapping.py).

## Quick map

**Search leaf** (`agents/hotel_search_agent/hotel_search_agent/`)

| File | What is there |
|---|---|
| `agent.py` | The prompt's location section is at `:162-202`. The S5 exception ("NAMED AFTER A CITY THEY ARE NOT IN") is at `:173-183`, and "leave `city` blank" at `:189-190`. |
| `geocode_tool.py` | Holds the model-facing `geocode_location` (GeoIntent form, Q07) and `geocode_core` (flat interface). Also: `_fill_place_from_profile(args, profile_in)` (`:1069`, destination carry-over, moved from the callback `inject_profile_geo_context`), `_complete_pending_place`, `_city_named_in_message` (fallback on the user's words), `geocode_city_needed` (a `mark_level` status of a `geocode_ambiguous` error), US ZIP forcing, homonyms (the leaf writes `pending_place`). `scripts/probe_geo_landmarks.py` calls the core with flat arguments. |
| `geo_resolver.py` | `city_needed_question` (`:247`), `_CLARIFY_MANY`, homonyms (`:486-525`), the inventory tier (`:58`). |
| `geo_guards.py` | `select_us_postal_anchor` (`:458`), and `STREET_SUFFIX_TOKENS` within `:417-514`. |
| `mapbox_client.py` | Geocoding v6 (`GEOCODE_URL` `:29`). It reads `context.country` and `context.region` (`:229-264`). |
| `response_bridge.py`, `contract.py` | The leaf's DataPart. `search_context` is the model for passing structured facts to the concierge. `response_bridge.py:1637-1638` relays `pending_place` into `profile_delta`. |

**Concierge** (`agents/b2c_concierge/b2c_concierge/`)

| File | What is there |
|---|---|
| `agent.py` | `_attach_outgoing_datapart` (~`:365`) puts `context_text` (EARLIER REQUEST / YOU ASKED / REPLY) **before** the user's words (`:380-386`), so the leaf reads them as one message; `_SYNTHESIS_INSTRUCTION` (~`:451`) and the synthesis call (~`:691`); anti-loop (~`:900`); bare-affirmative fast path (~`:1200`); triage call (~`:1226`); routing priority (~`:1328-1362`); clearing of `pending_place` (~`:1714`); other `is_bare_affirmative` uses outside the clarification route: greeting relaunch and `search_exhausted`. |
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
- Interface (Q07): tool `geocode_location(intent: GeoIntent = GeoIntent(), metro=None, profile_state_context=None, profile_location_hint=None, locale=None, language_hint=None, proximity_lat=None, proximity_lon=None, tool_context: ToolContext | None = None)`. Core `geocode_core(city="", zone=None, metro=None, country_code=None, raw_user_message="", ..., country_guess=None, region_named=None)`. The mapping is `_place_args(geo, claims, locale=, language_hint=) -> {city, zone, country_code, country_guess, region_named}`. Q08 extends it for `places[0].postal_code`; Q14 adds the chosen option's region after the mapping or in `_fill_place_from_profile`.
- Readers in `response_bridge.py`: `read_input_text(tool_context)` joins every text part (concierge prefix included); `read_user_words(tool_context)` returns the last text part. `_Claims` in `geocode_tool.py` has `anchored(ref)`, `country(value)` and the counters.
- Interface for Q08, Q14, Q15: `_place_args(geo, claims, locale=, language_hint=)` now chooses `zone_place` (the first place whose kind is not city or hotel) and `cities` (places of kind city, then the anchored `city` field). Q08's postal_code is read from zone_place, not from places[0]. Q14's region goes after the mapping or into `_fill_place_from_profile`, never into a callback argument (ADK drops undeclared keys).
- Interface (Q08): `geocode_core` gained two keyword parameters, `postal_code` and `zone_kind` (the GeoIntent kind of the zone place). `_place_args` now returns both. `postal_code` is read from the zone place, else from a city place, and checked against the input text with the new `_Claims.written`. A place that is only the code (« dans le 75009 ») becomes neither zone nor city. The `core` spy fixture in `test_geo_intent_mapping.py` sees both new keys.
- Interface (Q08): `GeocodeCandidate` gained `postcode`, `place` and `match_confidence`, all defaulting to "" so existing constructors still work. `mapbox_client` exports `ADDRESS_TYPES` ("address,street") and `POSTCODE_TYPES` ("postcode"). New helpers in `geocode_tool`: `_market_country(locale)`, `_postcode_match(candidates, code, city=, guess=, market=)` and `_with_postcode(zone, code)`.
- Interface (Q14): `geocode_core` has a new keyword `region_chosen: str | None = None`. `geocode_location` adds the key to the core arguments only when it applies, so the existing `core` spy fixtures still see the same key set otherwise. `_Claims(text, user_words='')` now has `.typed(ref)` and the counter `.city_conflicts`.
- Interface (Q17): `geocode_tool._valid_intent(intent) -> tuple[GeoIntent, bool, int]` returns (intent, raw-validated, repairs used) and never raises. New helper `geocode_tool._repaired(raw: dict) -> tuple[dict, int]` works on a copy. It removes a place only when its `kind` is a str outside `_PLACE_KINDS`. A null or non-string kind (list, dict) is left for validation to reject. `_PLACE_KINDS = frozenset(get_args(PlaceKind))` is read from the schema, so the repair follows when Q23 changes the enum. A test that spies on `_valid_intent` must pass the 3-tuple through.
- Metric (Q17): the geo_intent line is now `dayuse_metric=geo_intent agent=b2c_hotel_search valid=%d repaired=%d places=%d mentions_discarded=%d canonicals_rejected=%d countries_discarded=%d city_conflicts=%d ambiguity=%s carryover=%s`. `places` counts the places of the intent actually used, after a removal, not the raw count.

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
- Tests for async harness code: no pytest-asyncio in the repo, so use `asyncio.run` and monkeypatch `exp._TRACE_LOOKUP_DELAY_SECONDS = 0`. Fakes patch `exp._call_facade` and `exp._prime_profile`; the Langfuse fake exposes `async_api.sessions.get` and `async_api.trace.get`.
- Every Field description and every class docstring of geo_intent.py ends up in the tool declaration the LLM reads (the class docstring becomes the $defs description). They are prompt text, so rationale goes in comments or in the module docstring. To regenerate the snapshot after a model change, run `/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/python libs/b2c_common/b2c_common/geo_intent.py > contracts/geo_intent.schema.json` from the worktree. Run it as a file path, not with -m: the venv's editable b2c_common points at the main checkout.
- Concierge side (Q04): `agent._leaf_clarification` validates `response.pop('clarification')` with `Clarification.model_validate`. An off-contract object is logged and ignored, and the turn keeps its synthesis (tested). The template only applies on the search route when 'results' is absent from the response. `templates.clarification_response(clarification, language, asked=1)` and `templates.CLARIFICATION_MAX_ASKS = 2` are the public rendering entry points. `MAX_OPTIONS = 5` and `SCHEMA_VERSION = "1"` come from `b2c_common.clarification`.
- Every homonym option has a non-empty `city`, and its `label` is a verbatim substring of the leaf's text question (`geo_resolver._clarify_question`). Q04 can render the labels, or match a user's answer against them, without any fallback for an empty city.
- Test idiom: `agents/hotel_search_agent/tests/test_clarification_emission.py` has a reusable `_through_the_leaf(tool_response)` helper. It runs `capture_after_tool` and `emit_search_datapart`, then decodes through the real ADK converter and returns `(datapart, text)`. Q09 can extend it when it removes `pending_place`. To assert the `geocode_city_needed` status offline, monkeypatch `geocode_tool.mark_level`.
- Follow-up for Q09: it deletes `pending_place`. The homonym `Clarification` carries the same options, already validated (`region`, `country_code`, and `place_formatted` inside `label`), so it is a natural replacement for what `_complete_pending_place` reads.
- The template exit has route `template:clarification` in the turn metric and Langfuse metadata, with status ok and llm_calls=2, phases triage,leaf_llm. The guardrail span is `anti-clarification-loop` with status_message `anti_clarification_loop`, and it fires only when asked > 1. The text-based synthesis guard (`retry-clarification-loop`, extract_final_question) is unchanged for the leaf's free questions, and Q11 removes it.
- Test helpers (Q04): `tests/test_leaf_concierge_seam.py` has `_over_the_wire(tool_result)` (leaf capture_after_tool + emit_search_datapart + the real genai→A2A→genai converters) and `_concierge_answer(monkeypatch, parts, message)` (real spine, fake leg, fake triage, no LLM). Q07/Q09 can extend them. In agents/b2c_concierge/tests, the `fake_leg` fixture imported from test_spine_profile needs `# noqa: F811` on the parameter line itself, not on the def line.
- For Q12/Q13, exact versus approximate proof: the exact 'no option the geocoder did not return' guarantee is TestRendering::test_no_word_of_a_reply_comes_from_outside_the_object and test_every_option_line_is_one_label_of_the_object (agents/b2c_concierge/tests/test_clarification_template.py), plus the 2 seam tests. All run offline in pytest. The live evaluator clarify_options_from_geocoder remains the weak signal.
- Test helpers (Q05): `agents/b2c_concierge/tests/test_clarification_routing.py` has reusable helpers: an `mcp_calls` fixture that records every inline MCP call (patches `inline_tools._mcp_session`); `_seed(store, session_id, **fields)` to pre-seed the profile; `_ask(runner, session, fake_leg, clarification, message)` for a turn that ends on a clarification, which then sets fake_leg back to a results payload; `_turn_routes(caplog)` for the `route` of each turn metric.
- Contract (Q05): new `Triage` fields `answers_pending: str` ("yes" | "no", default "no") and `answer_option: int | None`, set only when answers_pending == "yes". The enum constant is `triage.ANSWERS_PENDING`. New helper `profile.chosen_clarification_option(pending_clarification, index) -> dict | None`. New keyword-only parameter `inline_tools._resolve_hotel_id(..., name_from_reference=True)`.
- Harness, for evals Q12/Q13: after Q05, the route of a clarification answer is `leaf:hotel_search`, even when the triage family is booking. A booking with no offer and no list, and no clarification pending, keeps route `inline:generate_booking_link` (degraded status) and the 'no list' template. In both cases `mcp-find_hotel_by_name` is never called with the raw message. `_derive_route` in `evals/langfuse_experiment.py`, which reads the triage family, is therefore wrong on these turns: assert on tool facts instead.
- Negative control without stash or reset, for a spine routing change: `cp agent.py <scratch>/agent.py.new`, then `git show plan/qa14707:agents/b2c_concierge/b2c_concierge/agent.py > agents/b2c_concierge/b2c_concierge/agent.py`, run the one test, then `cp` the new file back. The captured stderr shows the turn metric with the route taken.
- Metric line: `dayuse_metric=geo_intent agent=b2c_hotel_search valid=0|1 places=N mentions_discarded=N canonicals_rejected=N countries_discarded=N ambiguity=none|homonym|city_needed|too_vague carryover=<enum>`. Only counts and closed enumerations; a test checks that no word of the message appears. It goes through the shared `logging.getLogger('dayuse.metrics')`, so a test that monkeypatches `.info` sees every module's lines: filter on the prefix.
- Test helpers (Q07), `agents/hotel_search_agent/tests/test_geo_intent_mapping.py`: `_ctx(*texts, profile_in=, query_params=)` builds a real a2a→genai tool_context; fakes `_V6(by_query)` (records (query, country)), `_SearchBox(*candidates)`, `_Inventory(by_lat)`, `_patch(monkeypatch, v6, box, inventory)`; fixtures `metric`, `statuses` (mark_level), `core` (spy on geocode_core returning the flat arguments). Anchored-landmark pattern: v6 returns `V6_MISS` for « Gare du Nord, Paris » and PARIS for « Paris », and the Search Box returns the station. A v6 city candidate alone is accepted by the echo guard (its longest token is the city), so the station is never reached. In `tests/test_mcp_contract.py`: `_ToolContext(profile_in, query_params=, text=)` and `_arguments_sent(..., ctx=, guard=)`.
- For Q09: `_complete_pending_place` now runs inside `_fill_place_from_profile` (called by the tool) and reads `args['raw_user_message']`, the user's words. `TestPendingPlace` in `test_geocode_tool.py` calls `geocode_tool._fill_place_from_profile(args, {...})`: those are the tests Q09 deletes. `_city_named_in_message` still runs as a fallback on the user's words only. To move the St Paul's / champs élysées tests to a GeoIntent, call `geocode_location(intent=..., tool_context=_ctx(...))`. « Londres » -> « London » is a corrected name, so it triggers one `_city_coordinate('London')` lookup; mock v6 for that query.
- Negative-control recipe without touching the repo: write a pytest plugin in `<scratchpad>/<task>/` with an autouse fixture that monkeypatches the property away, then `PYTHONPATH=<scratch> .venv/bin/pytest -p <module> <tests>`. To run a patched copy of a test file you don't own: `.venv/bin/pytest -c pytest.ini --rootdir=. <scratch copy>` from the repo root. Used in Q07 for the mention check, the city mapping, `_iso2`, the city_needed flag, the user-words reader and MCP argument leaks.
- Test helpers (Q07 mapping): in `agents/hotel_search_agent/tests/test_geo_intent_mapping.py`, the `core` fixture spies on geocode_core and returns the flat args, `_ctx(*texts, profile_in=, query_params=)` builds a real a2a->genai tool_context, and `metric` collects the geo_intent metric lines. A mapping test needs no Mapbox fake when it uses `core`.
- Seam helpers (Q15), `tests/test_leaf_concierge_seam.py`: `_concierge_outgoing_message()` builds the real concierge outgoing parts for a homonym clarification answer (EARLIER REQUEST « un hôtel à Manhattan demain de 14h à 18h », reply « New York ») and round-trips them genai→A2A→genai; `_leaf_receives(parts)` wraps them in a tool_context stand-in. Q09 and Q11 can reuse them to keep the seam green.
- `FunctionTool(geocode_tool.geocode_location).run_async(args={'intent': ...}, tool_context=<SimpleNamespace with user_content>)` works offline with a plain stand-in context. Patch geocode_core with a spy on the `geocode_tool` module attribute.
- Test helper (Q08): `agents/hotel_search_agent/tests/test_postcode_resolution.py` has `_RecordedMapbox`, the real `MapboxClient` over an `httpx.MockTransport` that serves the H5 recordings, keyed by (q.casefold(), types). It applies a `country` param the way Mapbox does (drops other countries), records every request's params (`.requests`, `.queries`), and can drop a recording's first feature (`drop_first`). Fixture `mapbox` patches the client, an empty Search Box and an empty inventory. Q10 can reuse it to move the « near 11580 » tests onto a GeoIntent with `postal_code`.
- For Q10: keep « near 11580 » in the US without `select_us_postal_anchor`. Through DQ8 this works only when the model guesses US or the locale has a US region subtag ("en-US"). The production widget sends "en" (see the Q08 needs-human entry in HANDOFF: forwarding `entry_market_country` from the concierge would close the gap). Recorded facts: 11580's first Mapbox answer is Mexico City (MX), the second Valley Stream (US). 13001 marseille resolves to Marseille FR whatever the market, thanks to the named-city tie-break.
- Negative controls (Q08): the guard forbids env assignments, so the PYTHONPATH plugin recipe above is unusable there. Use a scratch edit of the production file, reverted by editing it back, and check `git diff --stat` before each commit to confirm nothing was left behind.
- Test helpers (Q14): `agents/hotel_search_agent/tests/test_homonym_option_region.py` contains a ready-made homonym fixture: ILLINOIS/MISSOURI candidates in the same inventory tier, about 400 km apart, so they really produce a clarify. It also holds PREFIX, the concierge's YOU ASKED text for Springfield, and CHOSEN, the profile_in after option 2 is picked. `agents/b2c_concierge/tests/test_clarification_routing.py` has `_SPRINGFIELD` and `TestOptionsSharingCityAndCountry._answer` (ask, then answer by index, with a leaf payload that keeps the city). Q09 can reuse both when it removes `pending_place`.
- Follow-up (Q14): Q09 and Q11 edit `_fill_place_from_profile` and the concierge clarification branch. They must keep three things: the `region_anchor` read placed after the city fill, the early return on a postcode turn, and the `profile.region_anchor = option.get('region') or None` line next to `country_anchor`. Q16 adds another concierge-owned profile field (`entry_market_country`). It can follow the same pattern: add it to the owned-slot list in `apply_profile_delta`, and keep it out of `_CONCIERGE_ONLY_KEYS` so it reaches `profile_in`.
- H3 (live replay) can now read `city_conflicts` on the leaf's geo_intent lines. A non-zero rate means gpt-4o-mini infers a city for a place that differs from the one the user wrote. Neither the region narrowing nor the city precedence has been measured live.
- Helper (Q16): agents/hotel_search_agent/tests/test_postcode_resolution.py now has `_through_the_leaf(args, ctx)`. It runs the real leaf chain: `inject_profile_geo_context` (injects locale etc. from profile_in), then `FunctionTool(geocode_location).run_async`, which drops undeclared args. It also has the constants NEAR_11580, VALLEY_STREAM and MEXICO_CITY. Q10 can reuse them to prove « near 11580 » without `select_us_postal_anchor`: profile_in {"locale": "en", "entry_market_country": "US"} gives Valley Stream with no country filter. Without the market, locale "en" gives Mexico City (test_without_the_market_a_bare_en_follows_mapbox_order).
- Helper (Q16): agents/b2c_concierge/tests/test_entry_market_country.py has a `store` fixture that patches `facade.get_profile_store` onto the autouse fakeredis store. The conftest only patches `agent_module.get_profile_store`, and the facade imports its own reference. It also has `_intake(session_id, body)`, which runs the real `_apply_native_context` and returns the stored profile. Chaining `_intake(session.id, body)` before `_run_turn` proves request body -> profile_in end to end, without the HTTP layer.
- Fact (Q16): The 13001 Marseille H5 recording contains an ES candidate (Ciudad Real) with the same postcode. With market ES and no city, `_postcode_match` picks ES, and the named city Marseille keeps FR. This is a usable fixture for 'named city beats the market'. There is no recording for « 75009 Paris » as a postcode query, so a city + 75009 tool-level test resolves nothing.
- H3 comparison (Q24): a run with zero hotels now shows as `skipped` on `hotels_within_km`; `min_hotels` scores the empty case. In the stored runs, 100 passes were vacuous. H3' pass rates are computed over runs that returned at least one hotel, and the number of skipped runs is reported beside them (re-scored counts in the Q24 review entries of HANDOFF.md).
- Dataset (Q24): `evals/datasets/b2c-qa-14707-2026-10-14.jsonl` item 10 (`qa14707-guard-gare-du-nord-asks-city-fr`) no longer has `must_ask_city` or `trace.geocode_city_needed`; it expects min_hotels 1 and hotels_within_km 3 km around the gare du Nord. Anything counting it as a city-question guard must stop; the gare de Lyon item remains the S5 guard.
- Test helpers (Q17): agents/hotel_search_agent/tests/test_geo_intent_mapping.py has `_run_tool(intent, *texts, profile_in=None)`, which runs the real FunctionTool(geocode_location).run_async with `_ctx`. It also holds the recorded H3 constants VERSAILLES_TEXT/VERSAILLES_INTENT, GARE_DU_NORD_EN_TEXT/GARE_DU_NORD_EN_INTENT and MONACO_DATE_INTENT, copied verbatim from scratchpad/h3/runs.json (traces 1dc8ced4, 79eea597, 492e82e6). Q18 and Q20 can reuse them.
- On macOS, use `sed -i ''`. A silent sed failure once left a test red and looked like a calendar-rot failure: tests/test_calendar_rot.py replays the whole suite, so any red test also fails it.
- To prove a test fails on the parent, copy the parent's source file over the module, run the test, then restore the file from a scratchpad copy. No git reset or rebase is needed.
- When a change alters a rule, grep the docstrings of the neighbouring functions (class, helper, mapper) for the old wording. Four docstrings had gone stale after the Q18 anchoring change.
- Design (Q18): the similarity check applies only to mentions and canonicals in `_Claims.anchored` (order: exact mention, exact canonical, similarity >= 0.85, counted in `mentions_fuzzy`). `written` (postcode) and `typed` stay exact, as the task requires. The 0.85 threshold would also accept a one-character slip on a short name (« Pari » vs « Paris » scores 0.89). That is intended, and the negative controls clear it with margin (Bruxelles 0.46, London 0.62).

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
  - Signature form for Q07, proved offline: declare `geo_intent: GeoIntent = GeoIntent()`. ADK's FunctionTool._preprocess_args converts the LLM's dict with model_validate only when the resolved annotation is the class itself or a non-string typing.Union. With `GeoIntent | None` the function always receives a plain dict. With `Optional[GeoIntent]` it receives a plain dict under `from __future__ import annotations`, and geocode_tool.py has that import. tests/test_geo_intent_contract.py declares its stand-in tool under that same import.
  - An argument that fails validation (unknown kind, a 3rd place, schema_version other than "1.1", extra key) is NOT rejected by ADK: ADK logs a warning and passes the raw dict to the function. Q07's wrapper must therefore handle `isinstance(geo_intent, dict)` itself, either with a tolerant model_validate or with a fallback. A test locks this pass-through.
  - Negative control for the conversion property: in an exploratory run, the forms `GeoIntent | None` and stringified `Optional[GeoIntent]` delivered a dict, while `GeoIntent = GeoIntent()` delivered a GeoIntent. So the dict-arrives-as-GeoIntent test can fail, and only the working form is locked. The LiteLLM tool schema keeps $defs/$ref and anyOf-null. jsonschema accepts it, but OpenAI accepting it has not been checked live: the first live leaf call in Q07 or H3 is the proof.
- **b2c_common dependencies**: `clarification.py` imports pydantic, but `libs/b2c_common/pyproject.toml` still declares only starlette. Per the plan, Q06 declares pydantic there; if Q06 does not, add it before merging.
- **ADK `State`** (`google/adk/sessions/state.py`) has no `pop` and no `__delitem__`. Clear a `temp:` key by assigning `None` and check with `isinstance` when reading it back.
- **Mapbox**: Search Box without `proximity` is biased by the caller's IP, so A/B replays must share one IP.
- **The LLM copies a sentence shown to it**, even when told not to. Imposed text is deduplicated in code, or never goes through the LLM (DQ2).
- **`evals/langfuse_experiment.py`**:
  - It used to post only the last user message (fixed by Q01, DQ4).
  - There is one trace per turn across A2A (OBS4). With multi-turn replay, facts must be scoped to the last turn.
  - `_derive_route` deduces the route from the triage family, and that becomes wrong after Q05. Assert on tool facts instead.
- **Shell**: in the user's shell, `cat` is an alias for `bat`, so use `command cat` or Read. Watch zsh's `$S:t` and `echo =====` (HANDOFF PORT1).
- **Data never touched, read or committed**: `.env`, `baseline/`, `dayuse_eval_pack/data/`, `.run-logs/`, `evals/reports/`. The eval cases are synthetic, or Raphael's test sentences.

- **Mapbox v6 fixtures (H5)**, in `agents/hotel_search_agent/tests/fixtures/mapbox_v6/` (recorded 2026-10-14, no `country` filter, `limit=10`, `autocomplete=false`). They show what Q08 and Q10 must handle:
  - `address_2_bd_poissonniere_75009.json`, 9 candidates:
    - the 1st is the right one: `2 Boulevard Poissonnière`, `context.postcode=75009`, `context.place=Paris`, FR, `match_code.confidence=high`;
    - no other candidate has 75009 (they have 75002, 92230, BE and CA codes). The postcode equality alone isolates the right one.
  - `postcode_75009.json`: Paris FR, then **Celina US**, then UA and EE. This is the FR/US tie of DQ8.
  - `postcode_11580.json`: **Mexico City MX first**, then Valley Stream US, then ES, UA and FR. Mapbox's ranking alone would send "near 11580" to Mexico, so the tie-break (the LLM's guess, then the market) is what keeps the US case (DQ8, Q10).
  - `postcode_13001_marseille.json`: Marseille FR first, then PE, ES, TR, UA and KR.
- **Harness traces (Q01)**
  - Trace scoping assumes one trace per turn (OBS4) and orders them by `timestamp`. After n replayed turns, fewer than n traces visible means the facts stay None (never the previous turn's). `/v3/chat` does not return a trace_id (only the SSE `progress` frame does), so there is no direct trace match.
  - `geocode_location` result: the facts read `obs.output` (dict or JSON string, with a `{"result": ...}` unwrap as a precaution), `diagnostics.options`, and `status_message == "geocode_city_needed"` or an error `geocode_ambiguous` with no option. The real shape of the ADK `execute_tool` output as exported to Langfuse could not be verified offline. At H1, check that `geocode_city_needed` / `tools_not_called` are not all `skipped`. A skipped result there means the observation name or shape differs.
  - `tools_not_called` stops polling once any observation of the last trace is visible. If the inline `mcp-*` observation is exported after the AGENT observation, a false green is possible. The `mcp-` prefix is the exact concierge name (`inline_tools.py:106`), and a test locks that a bare name does not count.
  - For Q04/Q05: the response contract has no structured clarification options and no trace_id. `clarify_options_from_geocoder` and `reply_differs_from_previous` work on `message` text only. A structured `options` field in the response or the leaf DataPart would let the check become exact.
  - Pre-existing, out of scope: CHANTIERS.md and HANDOFF.md note that `_call_facade` does not send `X-Dayuse-Synthetic`, so replay turns are untagged traces eligible for judge sampling. One-line fix in a file Q01 owns, but outside the task scope. Not changed.
- **Bare digit vs numbered homonym list**: a bare digit such as '2', answering the numbered list, still takes the `resolve_shortlist_ordinal` → booking branch (agent.py routing) whenever a shortlist from an earlier search is on screen. This predates Q04, but numbered options now invite it. Q05 must put a pending clarification (the option index) ahead of the ordinal/booking branches.
- **Pre-commit hook**: it runs `dayuse_guardrails.sh` on every commit (it printed 'Dayuse guardrails: OK' twice). A `git commit -F - <<EOF` heredoc message is accepted.
- **Leaf INSTRUCTION is a `str.format` template**: literal braces must be doubled (`{{}}`). The prompt tests in `test_agent.py` flatten whitespace with `" ".join(INSTRUCTION.split())` because phrases wrap across lines.
- **Task branch behind the plan**: task/Q07 lacked the plan's latest progress and plan commits (Q15 task file, HANDOFF amendments). They were merged with `git merge --no-edit plan/qa14707` (afdc1eb), without conflicts. The pilot's seam-test fix (64a32ae) is on the branch, so tests/test_leaf_concierge_seam.py appears in the diff against plan/qa14707 although Q07 does not own it.
- **`.worktreeinclude`** is untracked in the main checkout. It predates Q07 and is not part of it; leave it alone.
- **Postcode guards overlap (Q08)**: in the pipeline, a candidate with the wrong postcode (`2 Rue Poissonnière, 75002`) is refused by three guards at once: postcode equality, match_code confidence "low", and the echo. Only the unit test on `_postcode_match` isolates the equality. A future change to any one of these guards will not show up in the pipeline test alone.
- `git add -p` is not available. To split one file's diff into atomic commits, save `git diff <file>` to the scratchpad, keep the leading hunks with `head -N`, run `git apply --cached --check`, then `git apply --cached`. This works without changes as long as the kept hunks come first in the file.
- Test module basenames must be unique across agents/*/tests: two files named test_market_country.py (concierge + leaf) made the full pytest run error with an import-mode collision. Also, a relative import of a sibling test module (`from .test_x import ...`) works in agents/b2c_concierge/tests but NOT in agents/hotel_search_agent/tests when the whole suite runs (`tests.test_x` resolves to the concierge's package). Put leaf helpers' consumers in the same file, or copy the helpers.
- In `apply_profile_delta`, a flat or typed `set` of a slot with no field-specific branch is silently ignored. Only `{"op": "clear"}` goes through the generic path. To prove a slot is concierge-owned, test a clear op: a flat-value test passes even without the owned-slot entry (verified by negative control).
- Tooling (Q24): the re-score needs only runs.json (n_hotels plus stored scores). Run it with `python3 -I` from scratchpad/Q24. To compare evaluators across commits, load the old file with `git show <sha>:evals/langfuse_evaluators.py` into the scratchpad and import it with importlib, with PYTHONPATH=evals:. and the repository venv python.
- The raw recorded intents are in scratchpad/h3/runs.json, not in mapped.json, which holds only the mapped outcome. To find a tool input, search for `"kind": "date"` or the trace_id. The recorded tool inputs also carry top-level `city`/`language_hint` keys, which ADK drops before the tool runs (out of scope).
- Any repair applied to model output must check the value's type before a hash or set operation. Model JSON can put a list or an object in any field, and an unhashable value in a frozenset membership test raises TypeError instead of failing validation.
- The agent name `b2c_hotel_search` is on the `geo_intent` metric line, so a GDPR 'no word of the message' test must not use `hotel` as its sentinel word.
- A test meant to prove the exact-canonical step must assert `mentions_fuzzy == '0'` AND use a mention whose comparable text is not in the text as whole words. Otherwise the exact-mention step anchors it first and the test proves nothing about the canonical step.

## Context recommendations (end of run)
