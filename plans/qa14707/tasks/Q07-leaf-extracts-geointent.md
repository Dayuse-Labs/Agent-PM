---
id: Q07
title: The leaf extracts the place into a `GeoIntent`
phase: 3
model: opus
model_reason: "Source plan's model, kept: changes the interface of the leaf's central tool and its prompt; geo regression risk."
effort: xhigh
depends_on: [Q06]
parallel_batch: 3A
owned_files:
  - agents/hotel_search_agent/hotel_search_agent/geocode_tool.py
  - agents/hotel_search_agent/hotel_search_agent/agent.py
  - agents/hotel_search_agent/hotel_search_agent/response_bridge.py
  - agents/hotel_search_agent/tests/**
  - tests/test_mcp_contract.py
  - scripts/probe_geo_landmarks.py
resources: []
prerequisites: [E2]
context_budget: 45%
token_estimate: 4.7M
max_turns: 80
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests tests/test_mcp_contract.py"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "Mapping tests, Mapbox mocked: for A, `GeoIntent(city=Paris, places=[station \"Gare du Nord\"])` does **not** give the city_needed question and geocodes the station in Paris. For B, the city Versailles is kept."
  - "Test: a `mention` absent from the leaf's input text is discarded and counted in a metric that carries no message content."
  - "Test: with the concierge's EARLIER REQUEST prefix in the input (\"… Gare du Nord demain à 14h\" then \"Pari\"), the mention \"Gare du Nord\" is accepted as anchored."
  - "Test: \"Gare du Nord\" without a city still gives the city_needed question (case to keep)."
  - "Test (DQ6): \"gare de Lyon\" with `ambiguity.reason=\"city_needed\"` and no city gives the city_needed question."
  - "The existing geo tests (Budapest, La Défense, gare de Lyon, Saint-Paul, Manhattan) pass, through the internal core function. If an assertion must change, the report justifies it and a `deviation` entry is added."
  - "The leaf's prompt no longer tells the LLM to leave `city` blank for a place named after a city it is not in. The S5 rule is expressed as the `ambiguity.reason` rule (diff)."
  - "A case of `tests/test_mcp_contract.py` runs the before-tool chain after a `geocode_location(intent=…)` result: the `search_offers` arguments sent to the MCP hold no key outside the published schema."
  - "`scripts/probe_geo_landmarks.py` calls the new interface or the internal core (diff)."
  - "Test (Mapbox mocked): `country_named` is normalized by the code before it becomes the hard Mapbox `country` filter. \"fr\" gives \"FR\". A value that is not a 2-letter ISO code (\"France\", \"USA\", \"FRA\") is discarded, the mocked Mapbox call receives no `country` filter, and the rest of the intent is still geocoded."
  - "Test: `places[].country` and `city.country` go through the same `_iso2` normalization before they become `country_guess`. A malformed value degrades to no hint, never to a wrong scope."
  - "Test: when the `intent` argument fails `GeoIntent` validation (an unknown `kind`, three places), ADK 2.4 passes it to the function as a raw dict. The tool validates it with `GeoIntent.model_validate` and does not raise. It never uses the raw values: it goes on as with an empty `GeoIntent()`, so the carry-over from `profile_in` still applies. The failure is counted in a metric that carries no message content."
  - "Test: the leaf's real `geocode_location` FunctionTool, called with a dict `intent`, receives a `GeoIntent` instance. The parameter is declared `intent: GeoIntent = GeoIntent()`, not `GeoIntent | None`."
---

## Launch prompt
You carry out Q07 on the branch task/Q07. Read DISCOVERY.md and HANDOFF.md
of the plan first (decisions DQ1, DQ5, DQ6, Principle), then the files listed
in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- `phases/QA14707/DIAGNOSTIC.md` §1, reports 2A, 2B and 3. Leaf traces:
  - A: `geocode_location(city="", zone="Gare du Nord", raw_user_message="Gare du nord Paris")`;
  - B: `zone="Boulevard de la République Versailles", city=""`;
  - C: `zone="2 boulevard Poissonnière", city=""` (postcode thrown away).
- **The leaf's prompt**, `hotel_search_agent/agent.py:162-202`. It holds:
  - the exception "NAMED AFTER A CITY THEY ARE NOT IN" (`:173-183`);
  - "leave `city` blank if you don't know" (`:189-190`).
- **The tool**:
  - `geocode_location` (signature `geocode_tool.py:386`). `raw_user_message` is filled by the LLM; no code injects it.
  - The city_needed question is the `mark_level` status `geocode_city_needed` of a `geocode_ambiguous` error (`:596-599`).
- **Carry-over**: the before-tool callback `inject_profile_geo_context` (`:971-1028`) works on the flat `city`/`zone` keys.
- **Size**: `agents/hotel_search_agent/tests/test_geocode_tool.py` calls `geocode_location(` 81 times, and `scripts/probe_geo_landmarks.py:204` calls it too.
- **The leaf's input**: the concierge puts the EARLIER REQUEST / YOU ASKED / REPLY context **before** the user's words (`b2c_concierge/agent.py:380-386`), and the leaf reads it all as one message.
- **The `GeoIntent` model** from Q06: `libs/b2c_common/b2c_common/geo_intent.py` (v1.1: `postal_code`, `mention`/`canonical`, `ambiguity` = `reason` only). Its field descriptions carry the city rules.
- **Target mapping** (S-L plan §3):
  - `places[0].kind = city` → `city`;
  - another `kind`, except `hotel` → `zone`, with `city` from `places[0].city` (inferred or not, as today) or `city.canonical`;
  - `country_named` → `country_code` (hard filter);
  - a country not named → `country_guess`;
  - `region_named` → state anchor.

## Implementation notes
1. **Shape: a thin wrapper.** Keep today's body as an internal core function (for example `_geocode_core(city=…, zone=…, …)`), which the existing tests and `scripts/probe_geo_landmarks.py` call with their current arguments. Their assertions stay as they are.
   - The tool the LLM sees stays named `geocode_location` and takes `intent: GeoIntent` in place of `city`, `zone` and `raw_user_message`. The other arguments stay.
   - It maps the object, then calls the core.
2. **Mapping**, from the object to the core's variables (`effective_city`, `effective_zone`, `country_code`, `country_guess`). Everything downstream stays intact: echo, guards, inventory tier, guard #14, radius.
   - Adapt `inject_profile_geo_context` to the `intent` argument, or move the mapping before it, keeping the carry-over behaviour.
3. **Checks by the code**:
   - The `mention` must appear in the real message, compared ignoring case and accents. Otherwise the field is discarded and counted in a metric. That checks the LLM's claim; it is not language understanding. The metric carries no text (GDPR).
   - "The real message" is the leaf's whole input text, the concierge's prefix included. So on « Pari », the mention « Gare du Nord » from the earlier request is anchored.
   - `canonical` must geocode to a city with inventory (`_city_coordinate`).
   - The real message is **injected by the code** from the invocation, and never copied by the LLM again.
4. **`ambiguity`** (DQ6). `ambiguity.reason = "city_needed"` maps to the city_needed question: the code decides the question, the LLM only flags it. `homonym` and `too_vague` are read and logged, but not mapped: the geocoder keeps deciding homonyms (Q03).
5. **Prompt.** Rewrite the "place" section so that it fills the `GeoIntent`.
   - The named city always goes in `city`, even when it is written in the name of a place or an address ("paris Gare du nord", "Boulevard de la République Versailles").
   - The instruction "leave `city` blank" for a place named after a city it is not in disappears. It becomes the rule "`ambiguity.reason = city_needed`, no city" (DQ6).
   - The rule "a city inferred only when the place's name leaves no doubt" moves to the field description (Q06). So Gare du Nord without a named city has no city, and the code asks.
   - The question about the city stays decided by the code.
6. **Carry-over from one turn to the next.** Keep the current behaviour (filling from `profile_in`). The `carryover` field is read but not applied yet: that is S-L5, out of scope.

## Out of scope
- The address and the postcode (Q08).
- Removing `_city_named_in_message` (Q09): it stays as a fallback during this phase.
- `carryover` (S-L5).
- Mapping `homonym` / `too_vague`.
