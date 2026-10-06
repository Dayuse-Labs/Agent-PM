# Production knowledge preservation replay — 2026-10-06

The replacement must retain learned behavior from the legacy agent, including
FAQ and cancellation support. Old assistant answers are evidence to investigate,
not gold labels: several contain inconsistent policy or capability claims.

## Evidence and frozen references

- AgentB2C main: `07be07e447418c1b9b87fdd8b753b36a058a26b8`.
- Legacy main: `a08a7792ed95dedca6255b5c588a80a504dd6249`.
- Production export: **30,713 turns / 12,597 sessions**, February 20–October 6;
  **186,766 events**, captured October 6. All eligible turns retained.
- Log SHA256: `8d29049d67d0e9ea8c4325faaf10fbf0e7d3f670e873f53cfbfcebf145f4bcc6`.
- Event SHA256: `6e71c592d59b94d7236bef41c726b26b8c8ff51ed7345a56bc575250c327d8b6`.
- Export pins the initial ID ceiling and count, overlaps descending pages,
  deduplicates IDs, partitions events around the API offset ceiling, and verifies
  the final count and hash. This is not a transactional database snapshot.
- QA: https://gitlab.com/dayuse/dayuse/dayuse-com/-/work_items/14707.
- MCP tickets: https://gitlab.com/dayuse/dayuse/mcp-dayuse/-/work_items.
- Method: https://claude.dev/blog/automating-eval-design-and-hillclimbing/.
  Use production inputs, independently check graders, change one hypothesis at a
  time, and reserve unseen cases. Also retain a regression suite for past fixes.

## What is being compared

1. **Recorded legacy behavior and observed business KPIs.** Recompute the existing
   weekly-report formulas on the immutable export. Do not fabricate new clicks.
2. **Unmodified B2C main versus a candidate.** Same user turns, per-request historical
   clock, model, and shared MCP fixtures. Each conversation starts in a fresh
   synthetic session and runs sequentially; conversations may run concurrently.
3. **Behavioral regression assertions.** Trace each expectation to a reviewed fix,
   QA ticket or applicable source. Route correctness is not policy correctness.

Conversation hashes define dev/validation/holdout splits. Exact normalized
duplicates cannot cross splits. The first pilot uses only dev; no holdout transcript
has been used to develop the initial patch. Paraphrase clustering is not implemented.

1,462 sessions have explicit test prefixes; the remaining 11,135 are **unclassified**,
not certified organic traffic. Keep both populations visible. Do not exclude a
session just because it contains a common FAQ question: the legacy report's
synthetic-content heuristics include ordinary cancellation questions.

## Historical evaluations and feedback

The B2C Langfuse project has four historical datasets / 54 items. Their last
recorded runs predate this replay and are not measurements of today's candidate.
The feedback audit found seven `user-feedback` scores (two development, five
production-tagged), with too little provenance to infer a population satisfaction
rate. Human-labelled hallucination/relevance/distress scores are sparse; only
three exact human/judge pairs could be joined and verified. Do not claim a
calibrated general-purpose policy judge from that evidence.

Fetch trace details by ID and verify returned IDs before joining scores to dataset
items: a server-side `traceId` score-list filter was observed to be ignored. The
new replay's route annotations are by **Codex**, not human gold labels. A live
trace lookup verified the synthetic session ID, `eval-preservation` environment
and candidate release. Keep those experiments outside organic-traffic reporting.

## FAQ and cancellation preservation

`preservation_registry.json` versions 32 sourced requirements (18 search/dialogue,
14 FAQ/cancellation), each with its invariant, legacy/code references, a positive
probe, counterexample and ownership. It is an audit registry, not 32 passing tests.
Its execution statuses describe the initial audit; scored coverage must be attached
explicitly as work progresses. Relative `evidence/` references refer to the private audit archive; public repository and help-center links remain resolvable from the registry.

`faq_source_coverage.json` follows every one of the 104 legacy KB entries against
77 captured MCP articles: **21 normalized text matches, 46 central-intent matches,
five changed details, 20 partial matches, two conflicting entries and ten without
a match in the observed catalog**. All 66 same-ID entries have now been compared:
21 normalized matches, 39 core-equivalent translations, five changed/partial entries
and the previously identified cancellation conflict. Equal wording is not proof of
freshness, successful retrieval or correct model answers. No match is not proof of
product capability loss; hotel-specific fields or unprobed articles may cover it.

The 13 hardcoded FAQ entries now have a separate source mapping in the same file:
five central-intent matches, three partial matches, three conflicts and two not
found in the observed FAQ catalog (partner onboarding and the fixed US-city list).
They overlap the KB and are not 13 additional distinct intents. No old city counts,
fee values or blanket amenity guarantees are automatically restored.

Preserving source content can preserve a source defect: captured gift-card articles
disagree on France-only versus five-country use, and cancellation articles generalize
free cancellation versus non-refundable offers. Other differences concern overnight
prepayment, cancelling directly with a hotel and alternative-payment methods.
These discrepancies need an authoritative policy decision; source equivalence
is a separate axis from current policy correctness.

Preserve routing between new searches, public policy questions and support for an
existing booking; follow-up context; payment/guarantee/prepayment/booking-fee
distinctions; offer-specific cancellation deadlines; source freshness; market,
hotel and rate-plan identity; gift-card policy distinctions; and honest fallback.

Existing-booking actions need a separate capability contract. The legacy repository
contains optional support/ownership checks and cancellation machinery. The B2C FAQ
leaf only exposes `get_faq_conditions`. It must not claim to look up, modify, cancel
or refund a booking, or collect reference/email as if such a lookup were available.
Restoring executable cancellation is outside this patch and is not tested against
real bookings. The replay proxy cannot invoke cancellation tools.

The earlier audit identified disagreement between MCP cancellation text and the
published help article. Neither old generated answers nor a general article may
override the terms of a particular booking. Policy accuracy remains an unresolved
release check; a passing route or absence of hotel cards does not satisfy it.

## Historical pilot diagnostics — calendar-sensitive cases superseded

**Replacement pilots are complete under the corrected calendar mapper.** New
`calendar-v5-dev-*` and `calendar-v5-validation-*` directories each contain the
same 24 sessions / 61 turns per revision, with concurrency 2 and frozen application
SHAs. All 61 turn metrics join uniquely for each run. These replace the mixed-pilot
cost/result figures below; the older figures remain historical diagnostics only.

| Corrected-calendar measure | Dev main | Dev v3 | Validation main | Validation v3 |
| --- | ---: | ---: | ---: | ---: |
| Stock EUR disclaimer without cards | 18 | 0 | 22 | 0 |
| Actual observed LLM calls | 168 | 209 | 196 | 208 |
| Retained-attempt estimated LLM cost, USD | 0.078589 | 0.099055 | 0.098448 | 0.098494 |
| Non-OK turn status | 6 | 1 | 2 | 1 |

The validation routing check remains **44/52 → 52/52**, with nine ambiguous turns
unscored. That is a route check, not confirmation that all 52 answers are correct.
Repeated runs vary in cost and call path; no causal latency or cost gain is claimed.

**The mixed-pilot figures below predate a subsequently discovered fixture calendar
bug.** `availabilityDate` and `cutoffDeadlineUtc` had not been shifted with the
resolved search date. Those outputs must not support release or final cost/quality
claims. All affected search/inline conversations in the active full runs, holdout
review and baseline/v3 pilots have been archived and requeued. FAQ-only cases did
not use these offer dates; narrowly scoped routing diagnostics remain observations,
not a full policy or end-to-end correctness score. Corrected summaries are pending.

Same 24 dev conversations / 61 turns (23 unclassified sessions, 1 explicit test):

| Measurement | Main | Initial FAQ candidate |
| --- | ---: | ---: |
| Transport-complete turns | 61 | 61 |
| EUR disclosure appended with no hotel cards | 18 | 0 |
| Correct FAQ route on 15 support turns annotated by Codex | 7 | 14 |
| Actual observed LLM calls | 171 | 201 |
| Estimated LLM cost, USD | 0.080623 | 0.093314 |
| Turn metric status `degraded` | 5 | 3 |

The 15-turn routing subset is a development diagnostic, not an unbiased aggregate
quality score. More useful FAQ handling costs more than falling back to a greeting.
Both reported logical budgets have p95=3, while actual LLM calls have p95=5/4:
logical phase counts must not be described as measured model-call counts.

Do not attribute latency improvements to this patch: the pilot used different
concurrency, the candidate benefited from warmed fixtures, and local load differs.
Policy overgeneralization and one support agreement misroute remain in the pilot.

A second, three-line triage iteration explicitly keeps an agreement following
existing-booking support in FAQ. The same development pilot now routes 15/15 of
the reviewed turns correctly, with 0 spurious EUR disclosures and $0.100217 estimated
cost over all 61 turns. The 14→15 change alone is not evidence beyond model variance;
three repeated runs of the same five critical conversations each give main 7/15 and candidate 15/15. These are repeated measurements of the same inputs, not 45 independent examples. Policy
correctness remains ungraded and overgeneralized cancellation text is still a risk.

On a separate validation pilot (24 conversations / 61 turns), Codex annotated
the user inputs **before reading either version's validation replies**. 52 turns
had a sufficiently clear routing expectation; nine ambiguous turns were left
unscored. Main meets 44/52, v2 meets 52/52, with no routing regression on these
annotations. Spurious EUR disclosure: 21→0; retained-attempt estimated cost:
$0.096267→$0.098712 after rerunning the date-mapping-affected cases. Both have two degraded turn metrics. These remain routing
and behavior diagnostics, not human-reviewed policy accuracy or organic conversion.
Two cases per validation variant were rerun after the fixture date correction;
the routing counts stayed 44/52 and 52/52. Earlier dev-pilot cost figures above
predate this harness correction and are preliminary observations, not a final cost
comparison. The final holdout has not been used for development.

A third iteration fixes a concrete context break: the final FAQ synthesis previously
received only the latest user message and the leaf outcome, even though triage and
the FAQ leaf received prior user context. The same bounded user-only context now
also reaches synthesis and its clarification retry, tagged as unverified dialogue
rather than authenticated booking conditions. Offline end-to-end tests verify this
path and isolation between sessions.

On the 24-conversation / 61-turn dev pilot, v3 retains 15/15 annotated support routes,
zero spurious EUR disclosures, 205 actual LLM calls and $0.095766 estimated cost.
A manual Codex review also examined six post-hoc checks in four development
conversations, with two additional repetitions per candidate. V2 generalized one
booking's restrictions to most offers once and offered free cancellation despite
reported restrictions once; neither behavior appeared in the three v3 observations
of those cases. V2 succeeds on the other two repetitions itself: this is **not a
statistically established policy gain**. Both variants still sometimes state a
generic cancellation deadline for an existing booking. The source conflict and
policy release check remain unresolved; no aggregate policy-accuracy score is claimed.

The separate validation pilot also completes for v3: 52/52 annotated routes (main
44/52), zero spurious EUR disclosures, one degraded turn, 214 actual LLM calls
and $0.108868 estimated cost (main $0.096267). The same nine ambiguous turns stay
unscored. Extra context and stochastic call paths can change cost; this is not a
causal estimate of the context patch's marginal cost.

The first full baseline attempt and first candidate pilot hit staging HTTP 429 and
were invalidated. The replacement proxy freezes the tool catalog, shares successful
results and applies a global token bucket (8 burst, 72 requests/min). A provider
failure during a turn makes the replacement runner stop; HTTP 200 alone is not
proof of a valid replay. Both frozen full-corpus variants are **in progress**; no
complete full-corpus comparison, holdout win or launch approval is claimed.

The initial fixture gateway shifted search dates only. The correction also shifts
`get_hotel_details`, `compare_hotels` and `generate_booking_link`, and restores the
historical dates in their structured output and Dayuse URL query parameters. Before
resuming, 93 baseline and 6 candidate full-run cases with inline routes were set
incomplete and archived privately; each reruns in a fresh session. Two cases per
validation variant were similarly rerun. Unaffected completed cases are reused;
superseded outputs never count as successful retained attempts. Cached search
responses contained no affected `checkinDate` URLs. The correction and exact case
IDs are recorded in the private `harness-date-mapping-20261006.json` manifest.

## Calendar fixture integrity and limits

The revised mapper covers the actual MCP offer schema (`availabilityDate` and
`cutoffDeadlineUtc`) as well as `resolvedDate` and booking-link dates. An offline
contract audit checked **1,135 captured tool fixtures**, 13,264 date fields,
12,188 cutoff timestamps and 3,725 normalized hotel cards with no network calls.
The live calendar smoke then verified five dated hotel cards, two booking cards,
four booking/hotel URL dates and an undated upcoming quote. Article freshness
timestamps remain untouched. A test also runs the mapped offer
through the application's real hotel-card normalizer.

Undated details and comparisons have a different contract: they return upcoming
offers, not offers restricted to one requested date. The proxy does **not** inject
a date and silently change that scope. Instead it maps the snapshot's dates
relative to its acquisition UTC day (old captures use the original file timestamp,
now persisted with an explicit provenance label). Explicit-date calls use the
shared October 8 anchor. These two views do **not** prove identical inventory
across tools: cross-tool price/availability and historical cutoff eligibility remain
unverified, including intraday acquisition and timezone/DST effects. Do not grade
those as exact historical outcomes. Private MCP receipts identify undated upcoming
calls for review without logging user messages, arguments or credentials.

This is a comparative simulation on shared contemporary tool snapshots, not a
reconstruction of a historical booking environment. A stricter end-to-end inventory
comparison requires historical tool results or a server-side frozen clock/inventory.

## Independent holdout review

Before reading the corresponding outputs, a deterministic input-only sample was
frozen from the unclassified holdout: 12 FAQ/booking-hint and 18 other sessions,
78 turns in total, deduplicated by normalized conversation hash. The seed is
`dayuse-preservation-holdout-review-v1`. Codex annotated 73 routing expectations;
five ambiguous or counterfactual continuations remain unscored. Thirty case-level
content rubrics link to the preservation registry and cover dates, time-window
coverage, equipment, currency, age, booking support and capability honesty.
These are not human-approved labels or a prevalence-weighted sample.

The exact inputs, selection and oracles stay private. Both frozen revisions run this
additional cohort separately; it does not replace the full replay. No application
change may be tuned on these outcomes while still describing them as untouched
holdout evidence. Report routing and content review separately; a holdout label
alone never turns ungraded outputs into a quality score.

The corrected-calendar review is complete for both revisions: **30 sessions / 78
turns**. Per-case A/B presentation was randomized, and all content annotations
were saved before reading the version mapping. Style may reveal a version; formal
blinding is not claimed. The candidate application stayed frozen at `a47a31e`. One baseline content grade
was subsequently corrected from partial to pass after source inspection confirmed
its support phone number. This amendment was made after version unblinding; the
original annotation and evidence-based correction are retained privately. The
initial count was 6 baseline passes; the corrected count below is 7.

| Narrow review measure | Main | Candidate v3 |
| --- | ---: | ---: |
| Expected route met, among 73 scored turns | 54 | 65 |
| Case content criterion met | 7 | 11 |
| Case content criterion partially met | 4 | 4 |
| Case content criterion failed | 17 | 13 |
| Insufficient evidence for the content criterion | 2 | 2 |
| Stock EUR disclaimer without cards, among 78 turns | 23 | 0 |
| Actual observed LLM calls | 246 | 261 |
| Retained-attempt estimated LLM cost, USD | 0.139614 | 0.152049 |

The two unscored content cases concern unsupported amenity-retention evidence and
a date criterion lacking the original timezone. Partial is not pass. Five cases
improve in this ordinal review (three fail→pass, one partial→pass, one fail→partial);
no downward transition was observed on these narrow criteria. This does not
establish statistical superiority or global policy accuracy. All 78 turn metrics
joined uniquely per version; five routing ambiguities remain unscored.

Remaining failures include airport/location clarification loops, requested stay
windows not covered by shown offers, unanswered under-21 check-in restrictions,
booking-transmission questions answered as check-in timing, and long urgent
support dialogues resetting or promising quick resolution. Cancellation support
without an email link retains context better but still repeats an unavailable
route rather than reliably offering a concrete alternative. The candidate has
**13 failed and four partial content criteria** in this deliberately stratified
sample; this is not launch approval. Input-only labels and reviewed outputs stay
private in `holdout-review-oracles.json`, `holdout-content-review-ab.json`,
`holdout-review-results.json` and `holdout-review-paired-comparison.json`.

## Independent displayed-offer checks

`preservation_checks.py` checks explicitly annotated offer dates and stay windows
against displayed card fields. It imports no production filters or ranking code.
A stay from 12:00 to 13:00 requires an offer starting no later than 12:00 and ending
no earlier than 13:00. This differs from the inside-window predicate reproduced
by `scripts/eval_ranking.py`; agreeing with that predicate cannot validate the
customer's requested duration. Minute precision, missing evidence, multiple slots
and dated-card disagreement have independent positive and negative tests.

On a development-only source-input review, the first 18 unclassified conversations
matching an explicit time-range pattern yielded 15 eligible sessions / 24 annotated
turns. Three were excluded for flexible or contradictory boundaries, including an
"any time within" request that does not require occupying the whole interval.
Oracles were frozen before reading the corresponding full-replay outputs. Inputs,
hashes, row identities and retained checkpoints were verified before joining.

Both revisions have at least one displayed card not covering the annotated stay
on **10 main turns / 9 candidate turns**; the other **14 / 15 turns are unscored**
because there are no verifiable offers. No turn has every displayed card verified
to cover the interval. This is **not an improvement claim**: the 10→9 difference
comes from one candidate clarification with no cards, not a corrected match.
Four annotated date checks pass in both revisions (three distinct conversations),
which establishes only displayed-date agreement for those checks.

A mismatch is not automatically an incorrect overall answer: the New Haven case
explicitly discloses a time-window alternative in both versions. Other reviewed
replies call an 11:00–16:30 offer a match for an 11:00–19:00 stay or mix covering
and non-covering cards without identifying the mismatch. The private outputs are
`offer-constraint-dev-oracles.json` and `offer-constraint-dev-results.json`.
These are narrow development diagnostics, not a population quality rate or an
untouched holdout claim. No application tuning uses this new output review.

The same annotated row IDs were also joined to **recorded legacy hotel cards**,
without using old active filters or compatibility scores as labels. Legacy has
three turns where every displayed card covers the stay, 13 with a counterexample,
and eight unscored; all four date checks are unscored because the legacy cards do
not record `offer_date`. Among the three legacy coverage successes, the candidate
has two mismatches and one no-card clarification. The New Haven mismatch is
explicitly disclosed as an alternative. This is a useful preservation diagnostic,
but **not a controlled architecture regression estimate**: legacy had the original
inventory and historical code, whereas the replay uses today's captured supply.
The private join is `offer-constraint-legacy-comparison.json`.

One mechanism is verified beyond the historical-inventory confounder: the exact
Langfuse trace and synthetic session show a 10:00–17:00 request sent to MCP. Joining
its arguments to the captured upstream fixture by hash finds a 09:00–17:00 offer
for the same hotel whose displayed card shows 10:00–16:00. The production
`_offer_fits_exact_window` predicate explicitly rejects starts before the requested
start and accepts ends before the requested end. The independent full-stay check
therefore detects a concrete application filtering mismatch. This does not mean
that every flexible "within a window" request should use full-stay containment.
The exact private provenance is in `offer-window-trace-proof.json`; no application
change is folded into the frozen candidate during the full replay.

## What CI actually verifies

The `checks` job passed on `a777243`, but the optional `eval` job failed during
installation: `google-adk[eval]==2.4.0` pulled evaluator dependencies incompatible
with runtime `litellm==1.90.2`. No scenario ran. The Langfuse job skipped its steps
because its credentials were absent; its green job state was not an experiment.

The workflow now invokes the existing S08 LiteLLM battery on the same canonical
32 scenarios using the already-tested runtime/dev requirements, without that extra.
The S08 judge tally is not numerically comparable to the old ADK response-match
score; it is reported under its own rubric.
It verifies complete scenario count, reports its exploratory judge tally, and
stops services through an EXIT trap even on failure. Both optional live jobs check
MCP, Mapbox and model configuration; Langfuse also requires its project credentials.
Missing configuration is explicitly reported as **not executed**, with secret
names only. No credentials were uploaded or changed in GitHub. The repository's
current secrets list contains only the model and fleet-access keys, so hosted live
evaluation is still unavailable until configuration is supplied.

The replacement CLI was exercised locally against the live evaluation leaves on
one case per family: **8/8 scenarios executed**, exploratory judge tally 1 pass / 7
failures. This verifies the execution path, not a successful quality gate or all
32 scenarios. All workflow shell blocks parse; missing-config and complete-config
preflights were exercised with fake values, without exposing secret values.

These jobs remain exploratory and nonblocking as before. Their successful process
exit is not a release verdict, and the battery's budget counter records logical
phases rather than observed LLM calls. The production replay's independently
captured metrics remain the source for actual call/cost comparison.

## Existing business KPIs

Recomputed with legacy main's `conversation_weekly_report.py`, existing synthetic
filter, April 6–October 6 09:11 UTC: 10,665 sessions / 28,057 turns, 7,656 sessions
with results, 2,273 with clicks, session CTR **29.7%**. The formula named
`session_satisfaction_rate` is **89.1%**, but it is a proxy: a hotel compatibility
score >=85 with at most one warning, not a user satisfaction survey. Exact-slot
label rate: 68.4%; heuristic bug-flag rate: 5.0%.

The last-seven-day reference has 1,173 sessions / 2,798 turns, CTR 28.5%, the same
compatibility proxy 94.5%, exact-slot label rate 72.1%, heuristic bug rate 3.7%.
The new agent's compatibility values and labels cannot be assumed calibrated to
the legacy formulas. CTR/conversion require actual post-launch events, not replay.

## Running and resuming

All raw exports, fixtures, transcripts, per-turn results and metric captures belong
under ignored `baseline/` (private local files). Never commit production messages,
booking references, emails, credentials or `.env`. Use sanitized aggregate reports.

Tools:

- `python -m evals.production_corpus --help`: immutable read-only export.
- `python -m evals.replay_mcp_proxy --help`: loopback fixture gateway.
- `python -m evals.replay_runtime --help`: isolated local service launcher.
- `python -m evals.production_replay --help`: full-session replay and checkpoints.
- `python -m evals.replay_summary --help`: coverage and observed KPI aggregates.
- `python -m evals.replay_comparison --help`: paired aggregates on the same complete
  conversations; verifies corpus hash, case hashes, turn identities/order and run
  configuration. Refuses invalidated/superseded runs. Exit 2 means incomplete;
  exit 0 confirms descriptive corpus coverage, not answer correctness or release readiness.

Use a detached baseline checkout and a separate candidate checkout, distinct local
Redis databases/ports, the same LiteLLM model, a shared read-only proxy, and no
production metrics database. Langfuse traces must be tagged `eval-preservation`
with synthetic session IDs and release provenance. Secrets stay in private `.env`.

Resume with exactly the same manifest inputs. Completed cases are reused; partial
cases restart from turn one with a new session. Metrics join the retained attempt by its synthetic session ID; total estimated spend across all attempts is also reported. Do not reuse an invalidated run as evidence.

## Limits and remaining release work

- Source logs lack original GPS, timezone and user/account context. Locale is absent
  in 5,075 turns, currency in 5,190, domain in 3,010. Replay only request-derived
  fields; never use old model-generated active filters as native input.
- Naive legacy timestamps are treated as UTC. Search, detail, comparison and booking-link
  dates shift to shared current inventory (anchor October 8), then structured dates
  and Dayuse URL date parameters map back. This does not
  reconstruct historical availability, prices or booking-specific conditions.
- Mapbox is live. Tool results are frozen per identical request; different tool
  queries may retrieve different contemporary supply. Generated evaluation links
  contain replay dates and must not be treated as usable real-booking evidence.
- Fixed historical continuations can depend on the old assistant's replies. Mark
  such paths as counterfactual limitations rather than unquestioned agent failures.
- Complete both full runs, independently grade critical behavior, evaluate an
  untouched holdout, repeat critical cases to measure variance, and only retain
  improvements supported beyond run noise. Generic policy accuracy is ungraded.
- Search exact-window semantics and date retention across clarification remain
  separately identified QA risks. This FAQ patch does not claim to resolve them.
- Empty, duplicate and incomplete run comparisons now fail. Missing FAQ responses
  score `skipped`, never a false success for `max_hotels=0` or forbidden-text checks.
  Existing advisory CI jobs and permissive historic thresholds are not a release
  authorization and still need a calibrated coverage-aware release gate.
  The existing battery gate now checks its configured total and per-family counts,
  and refuses an absent battery or interrupted/empty unit suite. Its old quality
  floor is deliberately not rewritten to manufacture a passing release result.
