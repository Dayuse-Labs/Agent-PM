# PREREQUISITES — qa14707

| ID | Type | Prerequisite | Status | Evidence |
|----|------|--------------|--------|----------|
| DQ1 | decision | D-Q1: the `GeoIntent` is produced by the current search leaf, as a structured argument of `geocode_location` | done | HANDOFF |
| DQ2 | decision | D-Q2: a clarification question is rendered by template in the concierge, without synthesis | done | HANDOFF |
| DQ3 | decision | D-Q3: deploy `main` as soon as the reference replay H1 shows no regression | done | HANDOFF |
| DQ4 | decision | Q01 extends the eval harness: multi-turn replay on one session, tool facts read from the trace | done | HANDOFF |
| DQ5 | decision | `GeoIntent` v1.1 keeps `ambiguity.reason` and drops `ambiguity.options` | done | HANDOFF |
| DQ6 | decision | The S5 rule ("gare de Lyon" asks the city) is kept as a `GeoIntent` field rule in Q07 | done | HANDOFF |
| DQ7 | decision | S-L7f: Q10 removes `select_us_postal_anchor` | done | HANDOFF |
| DQ8 | decision | Country of a postcode: hard filter only on a named country; otherwise postcode equality, with ties broken by the LLM's guess and then the market | done | HANDOFF |
| DQ9 | decision | Q08's Mapbox v6 fixtures are real responses, recorded by Fabien (H5) | done | HANDOFF |
| H1 | manual | **Reference replay**, run by Fabien because it costs OpenAI, Mapbox and MCP calls.<br>**Sets**: the Q01 set plus the existing geo sets `b2c-geo-poi`, `b2c-geo-class-2026-10-06`, `b2c-dialogue-state` and `b2c-qa-2026-09-30`, 3× each.<br>**Builds**: first `cbe88b9`, then `main`.<br>**When**: after phase 1, because it needs Q01's set and the multi-turn harness (DQ4).<br>**Two checkouts**: the stack runs from a worktree at `cbe88b9`, then one at `main` (`bash scripts/run_local.sh`, prod models). The harness and the sets come from `plan/qa14707`.<br>**Environment**: a real Redis must run on `CONCIERGE_REDIS_URL`; without it `profile_store` degrades silently and the multi-turn cases fail for the environment, not the code. Every run goes out from the same egress IP (Search Box proximity bias).<br>**Commands**: seed with `scripts/langfuse_seed_datasets.py --only <stem>`, one stem per call, then run `evals/langfuse_experiment.py --datasets … --run-name …`.<br>It must be done before H3, which compares against it. | open | — |
| H3 | manual | **Replay after phase 3**, on `plan/qa14707`, with the same sets, setup and IP as H1, 3×.<br>**Bar**: no regression against H1 on the `regression_guard` cases, and Raphael's cases A, B and C green 3 times out of 3.<br>**If it fails**: don't start phase 4. The removals would weaken the fallback, and DQ1 is to be revisited (dedicated leaf S-L3/S-L4). | open | — |
| H5 | manual | **Real Mapbox v6 fixtures** (DQ9), recorded before phase 3 and committed on `plan/qa14707` under `agents/hotel_search_agent/tests/fixtures/mapbox_v6/`, one JSON per query, without a `country` filter (DQ8):<br>`2 boulevard Poissonnière 75009` (`types=address,street`);<br>`75009` (`types=postcode`);<br>`13001 marseille` (`types=postcode`);<br>`11580` (`types=postcode`).<br>Example: `curl -s "https://api.mapbox.com/search/geocode/v6/forward?q=75009&types=postcode&access_token=$MAPBOX_ACCESS_TOKEN" > agents/hotel_search_agent/tests/fixtures/mapbox_v6/postcode_75009.json`. Check that no file contains the token. | done | confirmed by the user on 2026-10-14; 4 files checked: valid JSON, `context.postcode`/`place`/`country` on every candidate, no token |
| E1 | environment | `node --version` ≥ 18 (the widget's `node:test` suites, also run by pytest) | done | `node --version` → v24.10.0 (2026-10-14) |
| E2 | environment | The main checkout's venv works: `/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest --version` | done | pytest 8.4.2; full suite 2416 passed on `main` c76f0a2 (2026-10-14) |

Types: decision · manual · environment. Statuses: open · done · dropped.

Checked by /orchestre:ready on 2026-10-14: phases 1 and 2 ready (dry run of phase 1 green: 2416 passed, ruff, mypy, guardrails, widget 16/16, seed dry-run); H5 done (fixtures checked), phases 1 to 3 ready; phase 4 waits for H1 and H3.
