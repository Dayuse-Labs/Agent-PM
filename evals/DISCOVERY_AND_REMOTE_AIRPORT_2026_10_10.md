# Conditional discovery and remote airport identity

Release decision remains **NO GO pending the broad fresh production comparison**. This is a grouped follow-up to `DECISION_POLICY_2026_10_10.md`, preserving the concierge-owned Redis profile, stateless A2A search leaf, read-only MCP retrieval and existing logical model phases. No new regex or geographic alias table.

## Behavioral changes

- An unresolved party total no longer blocks every search. If the destination is known, the leaf retrieves offers without guessed adult/child filters. The normalizer retains only offers for which provider adult/child limits allow at least one possible composition. This is **conditional discovery**, not proof that the actual customer's group fits. A deterministic message explains the remaining composition question. Missing destination still clarifies first.
- A changed total invalidates the old search context. Old adult/child counts remain correction context in the concierge but are omitted from the leaf and public effective filters while pending. Leaf deltas cannot invent them. An empty conditional shortlist cannot trigger an assertion of general unavailability or automatic widening. Booking has both route-level and direct-tool checks before any MCP call.
- A native airport identity can override remote device GPS for an explicitly named destination. The recorded Heathrow failure had an exact provider airport response but was rejected against the customer's Italian GPS. Only an exact airport name or native IATA code, provider ID, valid coordinates and unique identity qualifies. Conflicting provider points, terminals, shops and general POIs cannot use this exception. An explicit containing city remains a geographic constraint.
- Without GPS/city, a country hint permits one provider lookup, but only the same native airport evidence can resolve it. Other landmarks still request the containing city. This intentionally changes one old test's lookup count, not its rejection of the unanchored non-airport.

## Validation and deployment requirements

The retained Heathrow provider payload now resolves at the decision stage where the prior runtime rejected it. This offline counterfactual is not a new conversation evaluation. New tests cover stale count isolation, real A2A propagation, offer filtering, direct booking bypass prevention, remote airport/device precedence and negative identities. Test logs and raw replay evidence remain private.

Before release:

1. Freeze code and runtime configuration; report model overrides relative to Railway. Current Railway B2C triage/search are 4o-mini, synthesis is 5.2. The candidate evaluation configuration uses 5.2-low for triage, 4o-mini for search and 5.2 for synthesis. No deployment configuration has been changed.
2. Run the same real conversation trajectories against current production and candidate in isolated sessions. Preserve client locale, domain, currency, GPS and turn order. Report missing source context and date adaptation. Legacy export/Qdrant and preproduction MCP inventory are different retrieval systems, even with mirrored inventory; do not treat every hotel-list difference as an agent defect.
3. Review full trajectories and tool receipts: geography and requested subsets; date/window and minute alternatives; fee-inclusive price/currency; party eligibility; hotel/formula identity; amenity inclusion; comparison and references; no false availability. Report completion and clarification loops separately from factual integrity.
4. Replay all discovered major/critical failures after grouped corrections, then freeze and run the broad pack. Keep exposed cases separate from a fresh unedited holdout. A local test count or exposed replay pass cannot establish production superiority.
5. Require no major/critical known regression in release-critical journeys, no wrong destination/date/price/offer claim, and a clean exact-revision CI run. GitHub CI on the prior head was blocked before execution by account billing; local checks do not replace it.
6. Only after reviewed evidence and deployment approval: staged rollout with monitored failure/latency/cost gates and a verified rollback to the current deployment. FAQ/SAV remain phase 2 and must retain their existing production routing.

## Frozen v109 live replay

Runtime `fa14b9d8fd24c93eed74678033a443d9bc38d2cb`: **2 exposed conversations / 4 turns**, completed against live read-only MCP. The three-turn Los Angeles → bed/shower → LAX journey now searches and produces offers on each turn while retaining morning arrival/until18 and the unresolved group total. The Heathrow request from Italian GPS now returns five offers around the provider-verified airport. All selected beds on the bed/shower follow-ups are double or king, but the profile does not yet represent bedding as a durable independent constraint; this is not proof of complete bedding coverage.

**12 displayed offer occurrences** join to exact same-turn MCP hotel/formula/date/minute-slot receipts: no unmatched cards, price/fact mismatch or expired offer detected. Twelve distance calculations agree with the displayed origin; zero literal-minute mismatch in this narrow sample. Unknown composition remains unverified, so there are no confirmed occupancy checks to claim. Shower inclusion and being inside versus near an airport still need separate product validation.

Nonblind full-trajectory review by the coding agent: **one A, one B**. The B reflects repetitive composition wording and insufficient explanation of airport access; exposed cases and no fresh legacy arm mean **no production win-rate conclusion**. Last broad live results remain v107 and are not assigned to this runtime.

Validation: **3,250 offline tests pass**, one optional paid Langfuse test skipped; ruff, mypy84, guardrails and diff checks pass. Runtime source hashes were verified unchanged after replay. Nine physical model calls (five5.2, four4o-mini); measured model cost **0.0729432USD**. Infrastructure/Mapbox/MCP costs are not included in that model telemetry.

Accounted campaign total is **198.91661799USD**, including prior retained provisions; original ceiling200USD/reserve0.50 leaves **0.58338201USD**. No budget increase has been applied. Additional amount selection remains pending. Services are stopped, STOP restored, and no paid batch is unsettled. No merge, deploy or Railway write.

The proposed next30USD allocation is: up to12USD for a fresh same-window paired100-conversation run (the prior100-pair run cost11.35USD), up to6USD for critical-path diagnostics/model comparison, up to8USD for grouped-correction replays, and4USD contingency. These are dispatch caps/estimates, not guaranteed API invoice limits; observed spend and unpriced provisions must stop dispatch before the authorized cumulative ceiling. Run diagnostics before the full pack when unresolved blockers make a broad replay uninformative. No paid campaign is started by this document.
