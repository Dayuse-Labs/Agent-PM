"""OBS6 — run a Langfuse dataset experiment against a live b2c-concierge.

Attacks the agent through the stable `/v3/chat` HTTP facade (no dependency on
OBS2's in-flight libs/**/agents/** work). For each dataset item:

1. Primes a FRESH session's profile directly in Redis, using the SAME key
   format and JSON encoding as `b2c_concierge.profile_store.ProfileStore`
   (`b2c_concierge:profile:{session_id}`) — this is the N+1 replay pattern
   (evals/datasets/README.md): the item carries the profile accumulated
   BEFORE the turn under test, so only the final user message needs to be
   sent for the turn to be reproducible, without re-running every prior turn
   as a real (slow, costly) LLM call. `SessionProfile.from_dict()` is reused
   directly (read-only import from agents/b2c_concierge — the same pattern
   evals/battery.py already uses) so unknown profile keys degrade exactly
   like production: silently dropped, never crashing.
2. POSTs the last user message to `POST {CONCIERGE_URL}/v3/chat`.
3. Best-effort looks up the resulting Langfuse trace(s) for that session (the
   session id is unique per item+run, so a session holds at most the traces
   from ONE turn) to extract: the leaf's `search_offers` TOOL-observation
   input, and the concierge's triage GENERATION output (`family`/`pick`/
   `pick_position`). Bounded retries (Langfuse's OTel export is async/
   batched) — a miss degrades to `None` facts, never a fabricated pass (see
   evals/langfuse_evaluators.py).

Usage:
    .venv/bin/python -m evals.langfuse_experiment \\
        --datasets b2c/geo-poi,b2c/occupancy,b2c/language-robustness \\
        --run-name baseline-2026-07-30

Env: LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST (or BASE_URL) already used by the
services; CONCIERGE_URL (default http://localhost:8100, matching
scripts/smoke_e2e.py's convention); CONCIERGE_REDIS_URL (default
redis://localhost:6379/0, matching profile_store.py's default).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
CONCIERGE_URL = os.environ.get("CONCIERGE_URL", "http://localhost:8100").rstrip("/")
REDIS_URL = os.environ.get("CONCIERGE_REDIS_URL", "redis://localhost:6379/0")

# Mirrors b2c_concierge.profile_store's private key format — there is no
# public API for priming a session's profile from outside the process; this
# is the wire contract (Redis key + JSON-of-to_dict()), kept in sync manually.
_PROFILE_KEY_PREFIX = "b2c_concierge:profile:"
_PROFILE_TTL_SECONDS = 1800

# How long we're willing to wait for Langfuse's async OTel export to make a
# turn's traces queryable via the API before giving up (bounded — a miss is
# an honest `None`, not a crash, not a false pass).
_TRACE_LOOKUP_ATTEMPTS = 7
_TRACE_LOOKUP_DELAY_SECONDS = 2.5


def _ensure_concierge_importable() -> None:
    pkg_dir = str(REPO_ROOT / "agents" / "b2c_concierge")
    if pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)


def _item_attr(item: Any, name: str, default: Any = None) -> Any:
    """Works for both a DatasetItem (attribute access) and a local dict item."""
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _last_user_message(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    raise ValueError("item.input.messages has no user turn to replay")


async def _prime_profile(session_id: str, profile_delta: dict[str, Any]) -> None:
    """No-op when the item carries no profile — a turn-1 item legitimately
    starts from an empty profile, matching a brand-new session."""
    if not profile_delta:
        return
    _ensure_concierge_importable()
    from b2c_concierge.profile import SessionProfile  # lazy: needs the sys.path insert above

    import redis.asyncio as redis

    profile = SessionProfile.from_dict(profile_delta)
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await client.set(
            f"{_PROFILE_KEY_PREFIX}{session_id}", json.dumps(profile.to_dict()), ex=_PROFILE_TTL_SECONDS
        )
    finally:
        await client.aclose()


async def _call_facade(session_id: str, message: str) -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{CONCIERGE_URL}/v3/chat", json={"session_id": session_id, "message": message}
            )
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {"_transport_error": f"{type(exc).__name__}: {exc}"}


def _try_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _derive_route(family: str | None, response: dict[str, Any] | None) -> str | None:
    """Deterministic, code-owned mapping from the triage `family` (+ the
    response's own `booking_card` presence for the R9 confirm/refuse split)
    to the dataset's route vocabulary. NOT a scrape of the concierge's stdout
    log (`concierge_metric=turn ... route=...`) — that log line uses a THIRD
    vocabulary (`leaf:hotel_search`) tied to routing.py's internals, and
    scraping a log file would only work against a locally-tailed process,
    not a deployed instance. This mapping only uses facts already on the
    trace/response contract, so it works the same way against any target."""
    if family is None:
        return None
    if family == "booking":
        return "booking_confirmed" if (response or {}).get("booking_card") else "not_booking_confirmed"
    if family == "search":
        return "search_refinement"
    return family  # "faq" / "ack" / "details" / "compare" pass through as-is


async def _lookup_trace_facts(
    langfuse_client: Any, session_id: str, response: dict[str, Any] | None
) -> dict[str, Any]:
    """Polls the WHOLE session (never stops at the first non-empty trace
    list): one turn produces TWO traces exported independently and on their
    own schedule — the concierge's `v3.chat` trace and the leaf's
    `b2c_hotel_search` trace (OBS4, distributed tracing, hasn't landed yet).
    Stopping as soon as ANY trace is visible was confirmed live (2026-07-30)
    to sometimes catch only the concierge trace and miss the leaf's
    `search_offers` TOOL observation entirely — an honest-looking but wrong
    skip. So: keep re-fetching every attempt until `search_offers_args` is
    actually found, or the budget runs out."""
    search_offers_args: dict[str, Any] | None = None
    triage_family: str | None = None
    acted_family: str | None = None
    family: str | None = None
    pick: dict[str, Any] | None = None

    for attempt in range(_TRACE_LOOKUP_ATTEMPTS):
        try:
            session = await langfuse_client.async_api.sessions.get(session_id)
            traces = list(getattr(session, "traces", None) or [])
        except Exception:  # noqa: BLE001 — a lookup miss must degrade, never crash the run
            traces = []

        for trace_ref in traces:
            try:
                full = await langfuse_client.async_api.trace.get(trace_ref.id, fields="core,observations")
            except Exception:  # noqa: BLE001 — same degrade-not-crash posture
                continue
            for obs in full.observations or []:
                if obs.type == "TOOL" and obs.name == "search_offers":
                    args = _try_dict(obs.input)
                    if args is not None:
                        search_offers_args = args
                elif obs.type == "GENERATION":
                    parsed = _try_dict(obs.output)
                    if parsed is not None and "family" in parsed:
                        triage_family = parsed.get("family")
                        pick = {"pick": parsed.get("pick"), "pick_position": parsed.get("pick_position")}
                # The family the spine ACTED on, posted as OBS2 metadata by
                # `_emit_turn_metric` on the concierge's own AGENT observation.
                # See `family` in the return dict below for why this outranks
                # the triage generation's own answer.
                metadata = getattr(obs, "metadata", None) or {}
                if isinstance(metadata, dict) and metadata.get("family"):
                    acted_family = str(metadata["family"])

        family = acted_family or triage_family
        if search_offers_args is not None and family is not None:
            break
        if attempt < _TRACE_LOOKUP_ATTEMPTS - 1:
            await asyncio.sleep(_TRACE_LOOKUP_DELAY_SECONDS)

    return {
        "search_offers_args": search_offers_args,
        "pick": pick,
        # The family the spine ACTED on, not the one the triage LLM proposed.
        # These differ by design and the difference is the whole architecture:
        # "the LLM never routes" — triage only classifies, and code-owned
        # overrides in agent.py re-route on top of it (recovery-ack → search,
        # booking confirmation → booking, a shortlist ordinal → booking).
        #
        # Reading the generation's own `family` made `expected_route` blind to
        # every one of those overrides. Caught 2026-08-25 measuring P1-1: a
        # Spanish "vale" after an empty search was scored a FAILURE
        # (`family="ack"`) while the same trace's AGENT observation recorded
        # `family=search`, `route=leaf:hotel_search` — the spine had routed it
        # correctly. The metric was reporting on the classifier, not the router.
        #
        # `metadata.family` (not `metadata.route`) on purpose: `route` speaks a
        # third vocabulary tied to routing.py internals ("leaf:hotel_search"),
        # while `family` feeds the same code-owned `_derive_route` mapping the
        # dataset vocabulary already uses. `triage_family` stays the fallback
        # for a trace whose AGENT observation didn't make it to the exporter.
        #
        # ⚠️ This CHANGES what `expected_route` measures. Runs before
        # 2026-08-25 scored triage classification; runs after score real
        # routing. Do not compare the two directly.
        "family": family,
        "route": _derive_route(family, response),
    }


def make_task(langfuse_client: Any, run_label: str) -> Any:
    """Binds the Langfuse client + a run label (kept out of the session id
    namespace only to stay human-readable) into a TaskFunction closure."""

    async def task(*, item: Any, **_: Any) -> dict[str, Any]:
        item_id = _item_attr(item, "id", "item")
        item_input = _item_attr(item, "input") or {}
        messages = item_input.get("messages") or []
        profile = item_input.get("profile") or {}
        session_id = f"obs6-{run_label}-{item_id}"

        await _prime_profile(session_id, profile)
        response = await _call_facade(session_id, _last_user_message(messages))

        expected = _item_attr(item, "expected_output") or {}
        needs_trace = bool(expected.get("trace"))
        trace_facts = (
            await _lookup_trace_facts(langfuse_client, session_id, response)
            if needs_trace
            else {"search_offers_args": None, "pick": None, "family": None, "route": None}
        )
        return {"response": response, "trace": trace_facts}

    return task


def _print_summary(dataset_name: str, result: Any) -> None:
    """Pass rates over BOOLEAN (0/1) evaluations only — a "skipped"
    CATEGORICAL (evaluators.py's `_skip`) means the check couldn't run at
    all and must never be folded into a rate (that would silently inflate
    or deflate it)."""
    counts: dict[str, list[int]] = {}
    skipped: dict[str, int] = {}
    for item_result in result.item_results:
        for evaluation in item_result.evaluations:
            if isinstance(evaluation.value, int):  # _bool_eval always emits a plain 0/1 int
                counts.setdefault(evaluation.name, []).append(int(evaluation.value))
            else:
                skipped[evaluation.name] = skipped.get(evaluation.name, 0) + 1
    print(f"\n{dataset_name} — {len(result.item_results)} items")
    for name, values in sorted(counts.items()):
        rate = sum(values) / len(values)
        print(f"  {name:<32} {sum(values):>3}/{len(values):<3} ({rate:.0%})")
    for name, n in sorted(skipped.items()):
        print(f"  {name:<32} skipped x{n}")


async def _run(datasets: list[str], run_name: str, max_concurrency: int) -> None:
    from langfuse import get_client

    from evals.langfuse_evaluators import ALL_EVALUATORS

    langfuse = get_client()
    task = make_task(langfuse, run_name)
    for name in datasets:
        dataset = langfuse.get_dataset(name)
        result = dataset.run_experiment(
            name=run_name,
            run_name=run_name,  # without this, the SDK appends its own ISO timestamp —
            # the exact name is what makes two runs predictably comparable by name.
            task=task,
            evaluators=list(ALL_EVALUATORS),
            max_concurrency=max_concurrency,
            metadata={"concierge_url": CONCIERGE_URL},
        )
        _print_summary(name, result)
        print(f"  -> {result.dataset_run_url}")
    langfuse.flush()  # short-lived process — without this, queued events are lost


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets", required=True, help="comma-separated hosted dataset names")
    parser.add_argument("--run-name", required=True, help="Langfuse dataset run name (must be unique per run)")
    parser.add_argument("--max-concurrency", type=int, default=5)
    args = parser.parse_args()
    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        if not os.environ.get(key):
            raise SystemExit(f"{key} is not set — source your .env first (never hardcode keys)")
    asyncio.run(_run(args.datasets.split(","), args.run_name, args.max_concurrency))


if __name__ == "__main__":
    main()
