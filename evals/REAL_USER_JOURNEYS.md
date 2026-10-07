# Real-user regression journeys

`datasets/b2c-real-user-journeys.json` contains 24 synthetic customer goals grounded
in production conversation failures and the legacy regression suite. These are
**not organic customer transcripts**. Each goal carries the locale, market,
timezone, intended refinements, and observable requirements. Four goals are reserved
for validation; do not tune a prompt against their resulting conversations.

The October 7 campaign also replayed 41 retained historical sequences (139 turns
per agent), including all 24 previously selected geo sequences. Forty originated
in production logs with customer/QA traffic not conclusively classified. Booking
references were removed and cancellation requests made informational. Historical
calendar dates remain historical, so current availability is not a historical gold
answer. Fresh relative dates in the synthetic journeys provide a separate check.

## Comparison protocol

1. Record the deployed Railway service, image digest, release, role-specific models,
   timeouts and Langfuse project. A release variable alone does not prove the image's
   Git SHA. Use the widget proxy for B2C when that is the functioning customer path.
2. Compare legacy production and deployed B2C end to end with fresh sessions and
   independent cookie jars. Legacy uses exports/Qdrant; B2C uses the preproduction MCP, confirmed by
   Victor as an exact reflection of production. The retrieval paths and snapshot
   freshness can still differ; inventory identity has not been independently verified. Different hotel IDs alone do not establish a regression.
3. Compare B2C code/model variants separately on the same source revision, clock,
   isolated Redis databases and shared exact-argument MCP/Mapbox cache. Different
   arguments can still produce different inventory; this is not an identical-answer
   fixture for every request.
4. For adaptive journeys, the simulator sees the persona and actual dialogue/cards,
   but not the requirements used for grading. Its own historical customer messages
   use the assistant role; the hotel agent's replies use the user role. Check each
   generated message for customer role and persona adherence before forwarding it.
   Discard terminal text when the simulator stops. Neither a simulator stop nor an
   HTTP 200 is a success grade.
5. Read trajectories and tool arguments. Exclude simulator role/goal drift from
   quality scoring and keep its cost. The initial simulator pilot exposed role
   inversion and was quarantined; a model validator alone is not a gold oracle.
6. Grade constraints independently: actual search coordinates, date, whole requested
   stay, same-offer price/currency, amenities, occupants, hotel identity, and the
   usefulness of a clarification or disclosed alternative. No search/unknown fields
   are not passes. Verify prose against served tool evidence. Repeat critical cases.
7. Persist model and simulator costs before dispatching another batch. Unknown costs
   or interrupted accounting leave the ledger pending. Reserve covers late telemetry;
   this is not a provider-enforced spending cap. Include automatic Langfuse evaluator
   costs and failed pilots. Raw traces and credentials stay outside Git.

## Scope limits

The existing `preservation_registry.json` lists 32 requirements. This campaign's
live scenarios target parts of 23 of them. It does not exhaustively validate all
six months of fixes, browser/See-all behavior, session expiry, age boundaries,
gift cards, late/no-show flows, FAQ source freshness, or real authenticated booking
and cancellation actions. Existing offline tests remain an independent gate.

The audited run receipts, manifests, customer conversations, tool calls, model
outputs, cost ledger and exact execution scripts are private campaign artifacts.
The application changes do not deploy or select a different production model.

Method reference: [Automating eval design and hillclimbing](https://claude.dev/blog/automating-eval-design-and-hillclimbing/).
Use production tasks, separate development from validation, inspect the grader,
isolate changes, and retain counterexamples rather than optimizing a headline score.

## Feedback-derived follow-ups

`datasets/b2c-feedback-journeys.json` adds two fixed synthetic sequences (seven
turns): a massage question after a JFK search, and an afternoon search followed
by a budget refinement. These come from the two production-tagged Langfuse
sessions containing five negative `user-feedback` scores. The October 7 refresh
found seven such scores in total (five production, two development), with every
score joined to its exact trace. This is diagnostic feedback, not a satisfaction
rate or proof of organic customer traffic. Dates are adapted to tomorrow and
browser currency, domain and timezone are supplied explicitly.

## October 7 historical audit additions

`datasets/b2c-history-v18-regressions.json` adds nine **development-only synthetic
goals** from fresh historical failures: municipality/borough homonyms, contextual
budget replies, currency and hourly units, indifference to a neighborhood, explicit
airport cities, arrival/departure preservation, private spa access and adults-only
policies. This new adaptive file is a regression specification, **not a completed
scored run**. The verbatim 14-conversation replays and their candidate revisions
are documented separately in `PRODUCTION_PARITY_PROGRESS_2026_10_07.md`.

Do not continue an ordinal-selection scenario until the actual agent has produced
a shortlist. Answer necessary location clarifications first. A clock-compatible
offer need not have exactly equal endpoints. Hotel amenities alone do not prove
private/included services. Model grades are provisional until evidence review: the
October audit found major defects even among automatically graded A/B responses.
