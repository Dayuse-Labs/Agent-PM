# Incremental application controls

These 18 deterministic integration controls were executed with identical scripted model/tool outcomes against main fee667d and main + PR 2bdca9a: 3 pass / 15 assertion failures on main; 18 pass with PR. They measure code behavior under controlled inputs, not live-model quality. Neutral scripted replies cover extra calls so an exhausted test plan cannot manufacture a failure. Two controls already pass on main alongside the existing ordinal-budget protection.

The tests were extracted from the PR behavior tests and supplemented with public-function geometry and circuit probes. They are counterfactual controls, not an independent human acceptance suite. Do not report 15 failed assertions as 15 independently fixed customer problems.

To reproduce, copy this directory unchanged to a temporary directory, then execute pytest in each frozen checkout with its own agents/b2c_concierge, agents/hotel_search_agent, agents/faq_agent and libs/b2c_common on PYTHONPATH. Use --import-mode=importlib. No API key or network is used. A failing run on main is intentional evidence, never something to silence by changing the expected result.

Live comparison: 41 selected production-log/synthetic sequences, 278 turns across both variants, then 32 repeat turns on four cases. Source cache at identical arguments, same clock/models, independent sessions, no paid judge. These runs also demonstrate four open blockers; see docs/evaluations/pr-incremental-value-2026-10-07.md. Live customer transcripts, credentials and caches remain private.
