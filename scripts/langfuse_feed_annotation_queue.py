"""Feed the OBS7 human-calibration annotation queue from deterministic OBS3 scores.

Companion of `phases/OBS7-judges-online-annotation.md` §7 — the queue lets a
human score the same three dimensions the online judges score
(`human_hallucination`, `human_relevance`, `human_user_distress`, plus
`empty_shortlist` for quick triage), producing a judge/human calibration point
and, later, dataset items for OBS6.

Sources wired today:
  - `empty_shortlist == 1` (OBS3 score, any environment — see gap below)
Sources NOT wired yet (documented gap, not a bug):
  - `user-feedback == 0` — that score doesn't exist until OBS5 (👍/👎 feedback)
    ships; this script becomes a two-source feeder the day OBS5 lands, no
    structural change needed, just add the second `scores.get_many(name=...)`
    call below.

Known gap found 2026-07-31: as of this writing, `empty_shortlist` (like every
OBS3 score) has ZERO occurrences with `environment=production` on the live
Railway project — the concierge's last successful Railway deploy
(2026-07-30T10:28 UTC) predates both the OBS3 (13:46 UTC) and OBS4 (15:07 UTC)
merge commits, so the deployed prod build doesn't emit these scores yet. Real
`v3.chat` traces DO exist in prod (tracing itself is OBS2-era, already
deployed) — only the score layer is missing. Until Fabien redeploys
concierge, this script only finds candidates in `development` (real local-run
turns against real MCP/LLM, not synthetic). No environment filter is applied
by default for that reason; pass `--environment production` once the redeploy
lands to scope strictly to real production traffic.

**Queues by OBSERVATION, not TRACE** (bug found and fixed 2026-07-31): OBS4
intentionally removed `langfuse.trace.input`/`.name` — a trace object itself
carries no input/output anymore, everything moved to the turn's root
OBSERVATION. Queuing by trace_id therefore rendered "undefined" in the
annotation UI. `empty_shortlist` also fires on THREE different real-turn
shapes depending on how the turn was driven: the HTTP facade (`v3.chat` /
`v3.chat_stream`), an A2A-piloted concierge turn (`a2a.b2c_concierge`, e.g.
ops/testing pilots — see OBS4), or a direct ADK invocation with no wrapper at
all (`invoke_workflow b2c_concierge`/`b2c_faq`, e.g. eval-harness/experiment
replays — these have `input=None`, nothing to annotate). This script resolves
each candidate trace's real root observation among the first two shapes only
and skips the third (reported as `skipped_no_root`), rather than surfacing an
empty item.

Excludes synthetic traces: a trace's `tags` (not the score itself) carries
`"synthetic"` (b2c_common.observability.turn_observation). Cross-checked via
one `trace.get` per candidate trace — the scores API doesn't expose trace
tags directly, and candidate volume is small (deterministic guard/metric
scores, not raw traffic). Confirmed live 2026-07-31: even some `production`
`v3.chat` traces carry this tag (scripted post-deploy verification tours), so
this check is not optional.

Idempotent: skips any observation already present in the queue (by objectId),
querying `list_queue_items` once (paginated) before adding.

Env (same keys the services already use, never printed): LANGFUSE_PUBLIC_KEY,
LANGFUSE_SECRET_KEY, LANGFUSE_HOST. SDK: langfuse==4.14.1.

Usage:
    .venv/bin/python scripts/langfuse_feed_annotation_queue.py             # feed
    .venv/bin/python scripts/langfuse_feed_annotation_queue.py --dry-run   # list only, no writes
"""
from __future__ import annotations

import argparse
import sys

QUEUE_NAME = "obs7-judge-calibration"
REAL_TURN_ROOT_NAMES = ("v3.chat", "v3.chat_stream", "a2a.b2c_concierge")


def _get_queue_id(lf, name: str) -> str:
    queues = lf.api.annotation_queues.list_queues(limit=50)
    for q in queues.data:
        if q.name == name:
            return q.id
    raise SystemExit(f"annotation queue {name!r} not found — run the OBS7 setup first")


def _existing_observation_ids(lf, queue_id: str) -> set[str]:
    seen: set[str] = set()
    page = 1
    while True:
        resp = lf.api.annotation_queues.list_queue_items(queue_id, page=page, limit=50)
        if not resp.data:
            break
        seen.update(item.object_id for item in resp.data)
        if page >= resp.meta.total_pages:
            break
        page += 1
    return seen


def _is_synthetic(lf, trace_id: str) -> bool:
    trace = lf.api.trace.get(trace_id)
    return "synthetic" in (trace.tags or [])


def _real_turn_root_observation_id(lf, trace_id: str) -> str | None:
    """Find the trace's turn-root observation, or None (eval-harness replay, nothing to show)."""
    for name in REAL_TURN_ROOT_NAMES:
        resp = lf.api.legacy.observations_v1.get_many(trace_id=trace_id, name=name, limit=1)
        if resp.data:
            return resp.data[0].id
    return None


def _candidate_trace_ids(lf, environment: str | None) -> list[str]:
    trace_ids: list[str] = []
    page = 1
    while True:
        kwargs = {"name": "empty_shortlist", "value": 1, "operator": "=", "page": page, "limit": 50}
        if environment:
            kwargs["environment"] = environment
        resp = lf.api.scores.get_many(**kwargs)
        if not resp.data:
            break
        trace_ids.extend(s.trace_id for s in resp.data if s.trace_id)
        if page >= resp.meta.total_pages:
            break
        page += 1
    return trace_ids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="list candidates, write nothing")
    parser.add_argument(
        "--environment",
        default=None,
        help="restrict to one Langfuse environment (e.g. production); default is all environments",
    )
    args = parser.parse_args()

    from langfuse import get_client

    lf = get_client()
    if not lf.auth_check():
        raise SystemExit("Langfuse client not authenticated — check LANGFUSE_* env vars")

    queue_id = _get_queue_id(lf, QUEUE_NAME)
    already_queued = _existing_observation_ids(lf, queue_id)
    trace_ids = dict.fromkeys(_candidate_trace_ids(lf, args.environment))

    added = skipped_synthetic = skipped_no_root = skipped_already_queued = 0
    for trace_id in trace_ids:
        if _is_synthetic(lf, trace_id):
            skipped_synthetic += 1
            continue
        obs_id = _real_turn_root_observation_id(lf, trace_id)
        if obs_id is None:
            skipped_no_root += 1
            continue
        if obs_id in already_queued:
            skipped_already_queued += 1
            continue
        if args.dry_run:
            print(f"would add observation {obs_id} (trace {trace_id})")
            added += 1
            continue
        lf.api.annotation_queues.create_queue_item(
            queue_id, object_id=obs_id, object_type="OBSERVATION"
        )
        added += 1

    verb = "would add" if args.dry_run else "added"
    print(
        f"{verb} {added} observation(s) to {QUEUE_NAME!r}; "
        f"{skipped_already_queued} already queued; {skipped_synthetic} skipped (synthetic tag); "
        f"{skipped_no_root} skipped (no real-turn root observation — eval-harness/direct-ADK replay)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
