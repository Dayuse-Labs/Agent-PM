# Research memo — Multi-turn state management for a conversational hotel-search agent

> Research memo — 2026-07-23. Input for `reports/PLAN-RESOLUTION-GEO-MULTITURN-2026-07-23.md`.
> Scope: LLM-era dialogue state tracking (DST), delta-merge semantics and slot loss; industry practice in conversational travel/commerce; Google ADK state specifics; pagination/exclusion; time handling. Sources inline; verification caveats at the end.

---

## (a) Strongest DST / state-management patterns

### Pattern 1 — Explicit per-slot state operations (the "unchanged/updated/removed" enum), code applies the merge

The single most relevant research lineage for the audit findings. Pre-LLM DST already converged on emitting **operations per slot** rather than raw values:

- **SOM-DST** (ACL 2020) treats dialogue state as a fixed-size memory and predicts one of four operations per slot each turn: **CARRYOVER, DELETE, DONTCARE, UPDATE** — only UPDATE triggers value generation; everything else is deterministic ([paper](https://aclanthology.org/2020.acl-main.53.pdf), [code](https://github.com/clovaai/som-dst)). This is exactly the "unchanged / removed / updated" semantics: *carryover is the default*, so a slot can only be lost by an explicit (auditable) DELETE — never by omission.
- **Diable** (ACL Findings 2023, Amazon) reframes DST as **table operations**: state is a slot/value table; the model emits only `INSERT` / `DELETE` ops per turn (or "none"), and code applies them ([ar5iv](https://ar5iv.labs.arxiv.org/html/2305.17020)). Verified claims: "2.4× more time efficient than current state-of-the-art methods" (fewer I/O tokens), and — key against full-state re-emission — a model that "generates the full state from scratch at every turn … might learn wrong correlations amongst slots," whereas delta generation treats slots independently and is more robust to noise.
- **TripPy** (2020) is the copy-mechanism ancestor (values copied from user text, system text, or previous state) ([ar5iv](https://ar5iv.labs.arxiv.org/html/2005.02877)).

**Takeaway:** the leaf LLM should emit a *typed patch* (`{slot: {op: set|clear|keep, value}}`), and deterministic code should fold it into the Redis SessionProfile with carryover-by-default. Matches the existing "LLM extracts intent, code owns filter values" doctrine and fits the ≤3-LLM-calls budget (the patch rides on the extraction call already made).

### Pattern 2 — Delta-merge vs full-state re-emission: the actual trade-off

- **Delta/incremental risk = error propagation and "state momentum".** Recursive state models carry mistakes forward; **MoNET** names the failure where "wrong dialogue states are predicted because the previous prediction remains unchanged when it should be updated" ([arXiv 2211.05503](https://arxiv.org/pdf/2211.05503)). **AG-DST** mitigates with a two-pass "generate then amend" scheme ([arXiv 2110.15659](https://arxiv.org/abs/2110.15659)).
- **Full-state risk = spurious cross-slot correlations, token cost, and silent drops** — the model must re-produce every slot every turn, so any slot it forgets to re-emit is lost (the "date given turn 1, zone changed turn 2, date gone" bug is the canonical full-state-re-emission failure). Diable's results are the empirical counter-evidence to full re-emission.
- The hybrid practitioners converged on (LangGraph institutionalized it): **nodes/LLMs return partial updates; a code-owned reducer merges them per key** — "every node returns a partial dictionary — only the keys it changed… the executor merges these updates into the existing state without altering untouched keys" ([LangGraph state management](https://deepwiki.com/langchain-ai/langgraph-101/3.1-state-management)). The **12-factor agents** manifesto makes the same point: LLMs are stateless functions, "own your state and control flow," agent = stateless reducer ([12-factor agents](https://github.com/sahanatvessel/12-factor-agents)).

### Pattern 3 — Null vs absent must be three-valued (JSON Merge Patch shows why)

- **RFC 7386 JSON Merge Patch** is the standard delta format where **`null` means delete** and *absent means unchanged* ([RFC 7386](https://www.rfc-editor.org/rfc/rfc7386), [comparison](https://erosb.github.io/json-patch-vs-merge-patch/)). Documented limitation, directly relevant: because null = delete, "it isn't possible to change a key's value to null" — a two-state patch cannot express "user explicitly said no preference." Adopting merge-patch semantics for the profile requires either the SOM-DST-style operation enum or a sentinel (`DONTCARE`).
- LLM extraction work converged on **three-state semantics**: affirmatively stated / explicitly negated / not mentioned ([arXiv 2606.05970](https://arxiv.org/pdf/2606.05970)); also make fields optional rather than required, since "forcing a required field when data doesn't exist leads to hallucination" ([structured-output guide](https://techsy.io/en/blog/llm-structured-outputs-guide)).

### Pattern 4 — Function-calling DST (schema-guided, LLM-era)

- **FnCTOD** (2024) turns DST into function calling: per turn the LLM picks the domain "function" and fills slot arguments as JSON; zero-shot it let 7–13B models beat ChatGPT-era SOTA and improved GPT-4 by 14% ([arXiv 2402.10466](https://arxiv.org/html/2402.10466v2/)). **Caveat verified by reading it:** the paper does *not* specify full-state vs delta accumulation semantics, nor null-vs-absent handling — do not cite it for either merge strategy.
- Schema-guided lineage: slots defined by natural-language descriptions in a schema the model is prompted with ([description-driven DST](https://arxiv.org/pdf/2309.13448); survey, ACM Computing Surveys 2025: [arXiv 2402.18013](https://arxiv.org/abs/2402.18013)).
- For long, drifting sessions, **S3-DST** (Microsoft, ACL Findings 2024) adds "Pre-Analytical Recollection" — the model first restates what each prior turn established before updating state — to fight long-context slot loss ([arXiv 2309.08827](https://arxiv.org/abs/2309.08827)).

### Pattern 5 — Slot carryover and coreference as a first-class subtask

- Amazon's **Contextual Slot Carryover for Disparate Schemas** (Alexa, 2018) formalized deciding *which* prior-turn slots to carry into the current query ([ResearchGate](https://www.researchgate.net/publication/325592419_Contextual_Slot_Carryover_for_Disparate_Schemas)) — the production ancestor of "zone changed, keep the date".
- Coreference remains a named DST bottleneck ([Coreference Augmentation for Multi-Domain DST](https://arxiv.org/pdf/2106.08723)). "The second one" / "that hotel" → named-hotel slot resolution is this problem; the shortlist in the profile is the resolution table.

---

## (b) Industry evidence (conversational travel/commerce)

Honest headline: **no major travel player publishes the concrete state schema.** Verifiable:

- **Booking.com AI Trip Planner**: OpenAI's case study says the model "was trained to understand conversational prompts and map them to structured data like dates, locations, and property availability" ([OpenAI case study](https://openai.com/index/booking-com/)); the product retro contains no state-mechanism detail ([Booking Medium retro](https://medium.com/booking-product/8-weeks-to-innovation-lessons-from-building-booking-coms-ai-trip-planner-94adbf138748)).
- **Expedia Romie**: builds per-user "memories" across channels; the ZenML write-up notes the public material has "virtually no concrete technical insight into how state management actually works" ([ZenML](https://www.zenml.io/llmops-database/ai-powered-travel-assistant-for-trip-planning-and-personalization)).
- **Amazon Rufus**: custom LLM + RAG + query planner + streaming "hydration" of structured data; official blog does not describe multi-turn state handling ([Amazon Science](https://www.amazon.science/blog/the-technology-behind-amazons-genai-powered-shopping-assistant-rufus)).
- **Contextual query rewriting (CQR) is the documented production pattern** for follow-up turns — rewriting the current utterance into a self-contained query by resolving coreference/ellipsis against history — "widely used in many commercial systems, such as Bing and Microsoft's XiaoIce" ([e-commerce CQR](https://arxiv.org/pdf/2209.07584), [LLM conversational rewriting](https://arxiv.org/pdf/2502.15009), [survey 2024](https://arxiv.org/pdf/2410.15576)). Note: CQR is the *alternative* to an explicit profile — AgentB2C already chose the explicit-profile route, which is more auditable and cheaper per turn.
- **Benchmark evidence that agents lose constraints**: τ-bench (airline + retail) evaluates exactly multi-turn constraint/policy consistency, judging success by final database state; agents fail heavily on it ([τ-bench docs](https://evalscope.readthedocs.io/en/latest/third_party/tau_bench.html)).
- **Voice-assistant precedent**: Alexa Skills carry per-session key-value `sessionAttributes` echoed back on every request ([ASK docs](https://www.developer.amazon.com/en-US/docs/alexa/custom-skills/manage-skill-session-and-session-attributes.html)).

---

## (c) Google ADK specifics

- **ADK session state is natively event-sourced deltas.** All updates flow through events carrying `EventActions.state_delta`; `append_event()` applies the delta respecting prefixes. Three sanctioned write paths: `output_key` on an LlmAgent, manual `EventActions.state_delta`, or mutating `context.state` inside `ToolContext`/`CallbackContext` (auto-captured as a delta). Directly mutating `session.state` outside these "will likely NOT be saved" with Database/VertexAI session services ([ADK state docs](https://google.github.io/adk-docs/sessions/state/)).
- **Prefixes**: no prefix = session-scoped (per-conversation profile); `user:` = cross-session per user (currency preference, home city); `temp:` = discarded after the invocation (per-turn scratch like the raw LLM patch before merge); `app:` = global. Values must stay JSON-serializable basic types.
- **Instruction templating**: `{key}` / `{key?}` injects state into instructions per model call — a cheap way to hand the profile to the triage LLM without an extra call.
- **A2A: sessions are NOT shared with remote agents.** ADK maintainer (seanzhou1023): "two agents are not sharing the session but share the context. we already send historical events information as context to remote subagent" — via `RemoteA2aAgent._construct_message_parts_from_session()` ([adk-python discussion #2956](https://github.com/google/adk-python/discussions/2956)). *History* is forwarded automatically, but a **structured profile is not** — do not rely on the leaf re-deriving state from replayed events.
- **The pattern for "profile in / delta out" is explicit embedding.** Microsoft's ISE team evaluated shared storage vs embedded context vs per-agent state for A2A multi-agent systems and chose **embedded context**: "the coordinator retrieves context from the Context Store, optionally summarizes it, and embeds it directly in the message payload"; domain agents stay fully stateless; use `DataPart` objects with part-level `metadata.type` and a `schemaVersion` for independent evolution; growth capped with a 10-turn summarization strategy ([ISE blog](https://devblogs.microsoft.com/ise/a2a-context-passing-multi-agent-systems/)). This validates the AgentB2C architecture (profile as versioned `DataPart` in, patch as `DataPart` out; Redis owned solely by the orchestrator).
- For propagating context to tools, maintainers recommend `ToolContext.state` reads or `before_tool_callback` injection of arguments (keeps values out of the LLM) ([adk-python discussion #3743](https://github.com/google/adk-python/discussions/3743)).
- Cross-session preference learning is positioned in ADK as Memory (e.g., Vertex Memory Bank), separate from session state — orthogonal to the Redis profile; Vertex specifics conflict with the zero-lock-in invariant.

---

## (d) Pagination / "show me other options"

- **The repeated-item problem is measured.** He et al. (CIKM 2023, verified quotes): "a trivial baseline copies existing items from the current conversation history … and does not recommend new items"; standard evaluation "does not differentiate between repeated and new items"; when only *new* items count, "HIT@1 … dropped by more than 60% on average" ([arXiv 2308.10053](https://arxiv.org/abs/2308.10053)). An LLM asked for "other options" over the same context will happily re-emit the same hotels — **exclusion must be enforced by code, not the prompt.**
- **Standard recommender practice**: filter already-shown items at retrieval time ([exclusion of observed items](https://arxiv.org/pdf/2101.04526)). Concretely: keep `shown_hotel_ids` (and a cursor/offset) in the SessionProfile, pass it to `search_offers` as a server-side exclusion, and reset it whenever a constraint change invalidates the result set — the reset rule is the subtle part (zone change ⇒ reset; "cheaper ones" ⇒ keep).
- **Tool-design guidance (Anthropic)**: any tool that can return many results should implement "pagination, range selection, filtering, and/or truncation with sensible default parameter values" ([Writing effective tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)).
- **Exhaustion / over-constrained disclosure**: when constraints yield nothing (or the page is exhausted), the researched pattern is **progressive, priority-ranked constraint relaxation with explicit disclosure of what was relaxed**, or asking the user which constraint to relax; "users are more likely to choose a relaxed plan than the plan that strictly adheres to the specified constraints" ([Mixed-Initiative Relaxation](https://link.springer.com/chapter/10.1007/978-3-540-74141-1_8), [query relaxation](https://arxiv.org/pdf/1507.00819), [AWARE-US 2026](https://arxiv.org/pdf/2601.02643)). Never silently loop or silently re-show: say "those are all N hotels matching X in Y; want me to drop the pool requirement or widen the area?"

---

## (e) Time handling

Practitioner consensus is unusually crisp ([BoundaryML: Dates, Times, and LLMs](https://boundaryml.com/podcast/2025-11-11-dates-and-times) + structured-output write-ups):

1. **Always inject the reference date + user timezone into the extraction prompt** — LLMs have no clock; relative strings drift without "today" + zone.
2. **Make the LLM label, make code compute.** Emit a discriminated union — `AbsoluteDate` (Y/M/D + optional time) vs `RelativeDate` (ISO-8601 duration, e.g. "P1D") vs `RecurringDate` — "the model on labeling duty only; math, timezone lookups, and validation run in pure Python". For the profile this means storing both the resolved absolute date **and** a `date_reference` (resolution anchor + original expression), so "same day" survives a turn-2 zone change and can be re-validated if the session spans midnight.
3. **ISO 8601 everywhere in state and tool I/O**; never store relative strings ([James Tang](https://medium.com/@jamestang/best-practices-for-handling-dates-in-structured-output-in-llm-2efc159e1854)).
4. **Timezone**: default to the client's zone unless the user typed one; store what they meant, not what the server runs on. (Note: the front already sends `client_local_time`/`client_timezone` — currently ignored, cf. S12 README note.)
5. **Missing sub-components: ask, don't guess** — when a time component is missing, surface a follow-up rather than defaulting silently. For sub-hour times ("14:30"), the schema must have a time field distinct from an integer-hour enum, preserved verbatim through profile → leaf → MCP.
6. Deterministic resolvers exist as non-LLM fallback: **Duckling** (wit.ai) resolves deictic expressions against an explicit reference time ([announcement](https://medium.com/wit-ai/open-sourcing-duckling-our-probabilistic-date-parser-4351ee66c4ba)). Given an extraction LLM call is already paid for, Duckling is optional; the reference-date + label/compute split matters more.

---

## Synthesis — what this implies for SessionProfile v2

The research points at one coherent design: widen the profile schema to cover every audit-listed slot (named_hotel, zone/metro, absolute dates + `date_reference`, currency, GPS + distance_origin, `shown_hotel_ids`, cursor); have the leaf's existing extraction call emit a **typed patch with explicit per-slot operations** (`set` / `clear` / `dontcare`; absent = carryover, matching SOM-DST/Diable semantics and avoiding RFC-7386's null ambiguity); merge in **deterministic orchestrator code** (carryover-by-default so slots can never be lost silently, with logged clear ops); pass the profile to the stateless leaf as a **versioned A2A `DataPart`** (ISE embedded-context pattern; ADK-confirmed sessions are not shared); enforce exclusion lists/cursors and constraint-change resets in code; store all dates as ISO-8601 absolutes alongside the original expression and resolution anchor. All of this fits the ≤3-calls budget because the patch piggybacks on the extraction call.

## Could not verify / weak spots

- **FnCTOD** does not document delta-vs-full accumulation or null/absent semantics (confirmed by reading the paper).
- **Expedia, Booking.com, Rufus**: no public source documents their actual state schema or filter-persistence mechanics.
- **ADK**: no evidence of built-in structured-state synchronization to remote A2A agents beyond history-as-context; one third-party source claiming "session state is propagated" is contradicted by the maintainer statement in discussion #2956 — treat explicit DataPart embedding as required. ADK docs recently moved to adk.dev.
- **Alexa pagination**: session attributes verified generally; no official doc prescribing list-pagination-position specifically.
- MoNET and AG-DST characterizations rest on abstracts; Diable, He et al. 2023, ADK state docs, ISE blog, both ADK discussions, and the BoundaryML episode were quote-verified by direct fetch.
