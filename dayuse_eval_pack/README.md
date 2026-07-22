# Dayuse canonical eval pack

This directory is a portable black-box evaluation pack for comparing the
currently deployed Dayuse search agent with another architecture. It contains
no customer PII, raw production session identifiers, credentials or writable
production operations.

## What is covered

- `core`: the existing 95-case end-to-end search-quality battery;
- `geo`: country, homonym, airport and wrong-market regressions;
- `international`: focused language, country, amenity and multi-turn cases;
- `worldwide`: one scenario per supported frontend locale plus high-risk cases;
- `domain`: ccTLD response-language and card-currency probes;
- `multiturn`: 27 deterministic conversations across nine fragile families;
- `prod_wounds`: anonymized July 2026 failures, including GPS/distance anchor
  persistence, exact-place distance, fabricated budgets, named-hotel state,
  amenity contradictions, currency persistence, language, re-served shortlists
  booking-link recovery, repeated trade-off questions, truncated answers and
  duplicate tool calls when the adapter exposes tool telemetry.

Every assertion is outcome-based. The colleague's implementation does not
need to share Dayuse's internal class names, prompts or tool layout.

## Required HTTP adapter

The default adapter sends:

```json
{
  "session_id": "canonical-eval-...",
  "message": "user turn",
  "locale": "en-GB",
  "currency": "GBP",
  "_eval_clock": "2026-07-10T10:00:00Z",
  "native_context": {
    "geolocation": {"lat": 48.9, "lon": 2.4}
  }
}
```

The same `session_id` is reused across all turns of a case. The expected
response fields are:

```json
{
  "message": "assistant answer",
  "hotels": [
    {
      "id": 123,
      "name": "Hotel",
      "country_code": "FR",
      "city": "Paris",
      "latitude": 48.87,
      "longitude": 2.34,
      "distance_km": 3.2,
      "display_price": 120,
      "display_currency": "EUR",
      "amenities": ["Pool"]
    }
  ],
  "active_filters": {},
  "response_language": "fr",
  "ready_to_search": true,
  "requires_clarification": false,
  "booking_card": {"url": "https://..."}
}
```

An adapter may optionally expose `tool_calls` at the response root or under
`eval_debug.tool_calls`. This enables duplicate-call checks without requiring
the candidate to expose prompts, chain-of-thought or any other internal state.
If telemetry is absent, that warning-level check is marked as skipped and does
not fail the case.

`_eval_clock` is a test-only hook. The adapter should use it as the clock for
relative dates such as “today” and “tomorrow”. Production endpoints may ignore
it, but architecture comparisons should honor it for reproducibility.

If the new architecture uses a different API, put a thin adapter in front of
it. Do not weaken the case files to match an implementation-specific response.

## Run

From the repository root:

```bash
python -m eval_pack.runner \
  --endpoint http://127.0.0.1:5002/v3/chat \
  --suites core,multiturn,prod_wounds \
  --output eval_pack/results/local.json
```

Run the complete pack:

```bash
python -m eval_pack.runner \
  --endpoint http://127.0.0.1:5002/v3/chat \
  --output eval_pack/results/candidate.json
```

For an authenticated endpoint, inject the key from the environment. Do not
write it into the pack:

```bash
python -m eval_pack.runner \
  --endpoint https://example.internal/v3/chat \
  --api-key "$CHAT_API_KEY" \
  --pause-ms 800 \
  --output eval_pack/results/run.json
```

## Compare with production

First generate a baseline using the verified deployed commit, following
`baselines/README.md`. Then compare paired cases:

```bash
python -m eval_pack.compare \
  --baseline eval_pack/baselines/current_prod.json \
  --candidate eval_pack/results/candidate.json \
  --output eval_pack/results/comparison.json
```

The comparison classifies every case as `regression`, `improvement`,
`unchanged_pass`, `unchanged_fail`, `new_case` or `missing_case`.

## Inventory fixture

`fixtures/inventory_snapshot.jsonl.gz` is a minimized offline snapshot. It
contains hotel and rate-plan facts required for evals, while removing addresses,
photos, descriptions, reviews, order counts and customer data.

The bundled fixture comes from tracked repository exports. It is explicitly
not claimed to be current production truth. With read-only production database
access, regenerate it directly without querying sessions, conversations,
customers or bookings:

```bash
DATABASE_URL='postgresql+asyncpg://...' \
  python -m eval_pack.export_prod_inventory
python -m eval_pack.build_manifest
```

The URL is read only from the environment and is never printed. The database
transaction is read-only and selects only `hotels` and `rate_plans`.

If an approved catalogue export is provided as files instead:

```bash
python -m eval_pack.export_inventory --source-dir /path/to/fresh/export
python -m eval_pack.build_manifest
```

The fixture manifest records source modification times and SHA-256 hashes.

## Rebuild and validate the pack

The case builder below is for the original source repository because it imports
the historical batteries from `scripts/` and `src/`. The generated JSONL files
inside the ZIP are already standalone and do not need rebuilding.

```bash
python -m eval_pack.build_cases
python -m eval_pack.export_inventory
python -m eval_pack.build_manifest
pytest tests/unit/eval_pack -q
```

## Share the ZIP

Build the deterministic archive from the original repository:

```bash
python -m eval_pack.build_manifest \
  --archive eval_pack/dist/dayuse_eval_pack_20260721.zip
```

After extraction, the colleague can run from the archive root with the same
`python -m eval_pack.runner ...` commands. The archive contains the cases,
runner, comparator, schema, minimized inventory fixture, manifest and unit
tests. It never contains API keys or database credentials.

## Interpretation rules

- Deterministic failures such as wrong country, false distance, fabricated
  budget, lost explicit constraint or inactive inventory are blocking.
- Do not treat different wording as a regression by itself.
- Review every reported regression qualitatively before claiming zero
  regression or rejecting the new architecture.
- Keep the ticket/conversation clock frozen when adding date-sensitive cases.
- Never replay booking, cancellation, payment or other write operations against
  production.
