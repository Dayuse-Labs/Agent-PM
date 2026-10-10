# Decision policy consolidation — offline validation, not a release approval

This change adapts production's evidence-before-commit approach to the existing AgentB2C architecture. Production source inspected: `3093647403ec167a0f4ddc2e0bace05f9669d88f`, especially `geo_disambiguation.py` and `profile_sync.py`. It does not copy the legacy orchestrator, geographic dictionaries or regex parsing.

## Behavior and ownership

| Decision | Implementation | Ownership / constraints |
| --- | --- | --- |
| Resolve an exact geographic identity | Shared deterministic selector distinguishes a unique/dominant provider identity from adjacent homonyms. Explicit country/region filters run first; a deep locale-preferred homonym cannot gain the locale shortcut. | Search leaf; no model call, Redis access or inventory-based override of a dominant exact identity. Original provider ranks retained. |
| Resolve a neighborhood inside a city | Resolve their provider relationship together. A verified child carries its parent ID; otherwise one parent lookup joins by provider ID. A generic provider `City` suffix is normalized, without a geographic alias table. | Search leaf remains stateless. At most two distinct forward queries, as before; reverse membership still requires child AND parent. Unknown global neighborhoods and countryless administrative codes still clarify. |
| Receive an unresolved geographic response | Reject its entire geographic delta while retaining independent non-geographic updates. A failed resolution cannot install its proposed confirmed place. | Concierge alone owns and persists the profile. Customer intent already accepted before dispatch is preserved. |
| Select a day before other clarifications | One date reducer arbitrates literal single-day evidence, period extraction and carried state. A period label quoting only `demain` cannot erase the explicit date; actual multi-day ranges remain unresolved until a day is chosen. | Concierge; same timezone/date parser and existing model phases. No new regex or model repair loop. |

A2A/DataPart transport, LiteLLM, read-only MCP tools, Redis ownership, model configuration, booking authorization and offer-integrity guards remain unchanged. FAQ/SAV remain phase 2.

## Validation

- **3,232 offline tests passed**, one optional live Langfuse test skipped; ruff, mypy (83 source files), Dayuse guardrails and diff checks passed.
- Added integration/negative tests cover date correction across an existing pending week; other date endpoints; rejected geographic deltas; explicit-country precedence; nearby homonyms; child-parent identity and membership; false parent labels/IDs; and countryless administrative codes.
- One old assertion changes intentionally: an unresolved child is now queried before its parent. The test still requires no accepted area, no parent-city substitute and preservation of the requested subset.
- Resolver-only counterfactual on **290 retained city geocoder responses**: **no changed decisions** with the replay's recorded country constraint and without locale/GPS priors. This is a regression observation, not evidence that 290 conversations are solved.
- **14 retained child-parent queries**: identical accepted identities / rejected outcomes before and after. This includes provider-based abbreviation handling; an initial regression found during development was fixed before delivery.
- **Two captured v107 triage outputs** mislabeled the literal `demain` as `range`. Feeding their exact current messages and recorded reference date through the new date decision yields **2026-10-11**, with no pending period, in both cases. Only the decision stage was replayed; there were no fresh model completions, hotel searches or generated responses.
- Private evidence: `production_parity_v18/batch-v108/offline-decisions.private.json` and local test logs. Raw conversations/provider payloads are not committed.

## Remaining release limits

**NO GO remains.** The last complete live campaign is still v107 (`0e32cc0`), reported in `PRODUCTION_PARITY_2026_10_10.md`; its grades do not validate this new runtime. The changes do not establish superiority over production or complete preservation of six months of fixes.

Adult/child clarification loops, private-versus-property amenities, geographic/hotel spelling recall, some airport/area interpretations and comparative wording remain open. In particular, the cached Al Mankool / Dubai resolution remains unresolved; no successful live geographic replay is claimed here. The shared confidence policy did not change the 290 cached city decisions.

No additional paid evaluation was dispatched. Accounted budget remains **198.84367479 USD**, including retained provisions; the existing **200 USD** ceiling and **0.50 USD** reserve leave **0.65632521 USD**. Services remain stopped and STOP remains present. A fresh end-to-end replay requires funded headroom. PR stays draft; no merge or deployment.
