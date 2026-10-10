# Conditional discovery and remote airport identity

Release decision remains **NO GO pending fresh end-to-end evidence**. This is a grouped follow-up to `DECISION_POLICY_2026_10_10.md`, preserving the concierge-owned Redis profile, stateless A2A search leaf, read-only MCP retrieval and existing logical model phases. No new regex or geographic alias table.

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

The proposed additional evaluation ceiling is still awaiting the user's amount selection. A two-case/four-turn smoke is prepared within the existing residual budget only; it is not the full production comparison. No automatic paid reruns, merge or deployment.
