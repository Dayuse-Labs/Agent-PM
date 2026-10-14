---
id: Q10
title: "Removal: US ZIP by regex (S-L7f)"
phase: 4
model: sonnet
model_reason: "Source plan's model, kept: a bounded removal, replaced by the `postal_code` and the country rule of Q06-Q08."
effort: medium
depends_on: [Q09, Q16]
parallel_batch: 4B
owned_files:
  - agents/hotel_search_agent/hotel_search_agent/geo_guards.py
  - agents/hotel_search_agent/hotel_search_agent/geocode_tool.py
  - agents/hotel_search_agent/tests/**
resources: []
prerequisites: [E2, H1, H3]
context_budget: 30%
token_estimate: 1.6M
max_turns: 40
verification:
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/pytest -q agents/hotel_search_agent/tests"
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/ruff check ."
  - "/Users/fabiendauvergne/Projects/AgentB2C/.venv/bin/mypy agents libs"
  - "bash scripts/dayuse_guardrails.sh ."
definition_of_done:
  - "`git grep -n select_us_postal_anchor -- agents libs` returns nothing, and the `US` forcing has disappeared from `geocode_tool.py` (diff)."
  - "Test: \"2 boulevard Poissonnière 75009 Paris\" and \"hotel 13001 marseille\", with no country named, stay in France."
  - "The assertions of the \"near 11580\" tests pass without change."
  - "No new regex or word list in the diff."
  - "Test (H5 fixture `11580`, Mapbox mocked, after the removal): a GeoIntent with postal_code \"11580\", no country named and no model guess, with profile_in `locale: \"en\"` and `entry_market_country: \"US\"`, is searched in the United States, and no Mapbox call carries a `country` filter."
---

## Launch prompt
You carry out Q10 on the branch task/Q10. Read DISCOVERY.md and HANDOFF.md
of the plan first (Principle, DQ7, DQ8), then the files listed in Useful context.
Change nothing outside owned_files. Ask no question:
if you are blocked, finish with the status blocked and say why.
Return your report in the requested format: status, changed files,
deviations from the plan, findings useful to the next tasks.

## Useful context
- **`geo_guards.py:417-514`**: `select_us_postal_anchor` and `STREET_SUFFIX_TOKENS` (English only). Any 5-digit number in the text is read as a US ZIP.
- **`geocode_tool.py:671-675`** forces `country_code="US"` when the model gives no country. It comes from the prod bug "near 11580", geocoded outside the United States.
- **Latent defect**: every French postcode is taken for a US ZIP (`phases/QA14707/DIAGNOSTIC.md`).
- **S-L7f.** `phases/SL7-retraits-regles-langage.md:26` lists this rule as S-L7f, pending Fabien's decision. **DQ7** is that decision: remove it.
- **The country rule** of a postcode (DQ8, implemented by Q08): hard filter only on a named country; otherwise postcode equality, with ties broken by the LLM's guess and then the market.
- **Line numbers** are those of `main`, before phases 3 and 4: search by name.

## Implementation notes
- Delete `select_us_postal_anchor`, `STREET_SUFFIX_TOKENS` if it has no use left, and the `US` forcing.
- The existing tests of the bug "near 11580" are the specification. Their meaning must hold: a user of the US market who gives a ZIP is searched in the United States, through the DQ8 rule (the LLM's guess and the market break the tie). Adapt the inputs (a `GeoIntent` with `postal_code`), not the assertions.

## Out of scope
The other rules of `geo_guards.py` (S-L7).
