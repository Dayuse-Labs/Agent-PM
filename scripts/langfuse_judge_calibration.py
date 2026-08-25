"""Compute the OBS7 judge/human calibration point — and create the pairs it needs.

Companion of `phases/OBS7-judges-online-annotation.md` §7. The DoD asks for a
"premier point de calibration (accord judge/humain)": for each dimension, do the
online LLM judge and a human annotator agree on the SAME observation?

Why this script exists at all (the structural problem, found 2026-08-25)
-----------------------------------------------------------------------
The calibration point was impossible for a reason that more traffic would never
have fixed. The three evaluation rules each sample **independently at 5 %**, and
the human annotation queue was fed from a *different* source entirely
(`empty_shortlist == 1`, see `langfuse_feed_annotation_queue.py`). So the judges
and the humans were scoring **disjoint sets of observations**. Measured live on
2026-08-25: 14 human annotations (2026-07-31) and 3 judge scores (08-24/08-25),
with **zero observations in common**. Nothing to correlate, at any n.

The fix is to stop hoping the two samples collide and instead **feed the queue
from the judges' own output**: queue exactly the observations that already carry
a judge score. That is `--queue-missing`. Once a human annotates them, the same
observation carries both scores and the agreement becomes computable.

Direction matters: judge-scored -> queued for human. The reverse (make the judge
score the already-annotated observations) is not possible — evaluation rules only
apply to newly ingested observations, and there is no backfill on this instance.

Score-name pairing (judge score is named after the RULE, not the evaluator)
--------------------------------------------------------------------------
    obs7-hallucination-v3chat   <->  human_hallucination    NUMERIC 0-1
    obs7-relevance-v3chat       <->  human_relevance        NUMERIC 0-1
    obs7-user-distress-v3chat   <->  human_user_distress    BOOLEAN

Reading the output: for the numeric dimensions, both the mean absolute error and
a thresholded agreement are reported, because they answer different questions.
MAE says "how far apart are they"; agreement at 0.5 says "would they have made
the same call". A high MAE with high agreement means the judge is directionally
right but badly calibrated in magnitude — worth a prompt fix, not a rewrite.

Env (same keys the services already use, never printed): LANGFUSE_PUBLIC_KEY,
LANGFUSE_SECRET_KEY, LANGFUSE_HOST. SDK: langfuse==4.14.1.

Usage:
    .venv/bin/python scripts/langfuse_judge_calibration.py
    .venv/bin/python scripts/langfuse_judge_calibration.py --environment production
    .venv/bin/python scripts/langfuse_judge_calibration.py --queue-missing --dry-run
    .venv/bin/python scripts/langfuse_judge_calibration.py --queue-missing
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict

QUEUE_NAME = "obs7-judge-calibration"

# judge score name -> (human score name, dimension label, is_boolean)
DIMENSIONS: dict[str, tuple[str, str, bool]] = {
    "obs7-hallucination-v3chat": ("human_hallucination", "Hallucination", False),
    "obs7-relevance-v3chat": ("human_relevance", "Relevance", False),
    "obs7-user-distress-v3chat": ("human_user_distress", "User Distress", True),
}

# A numeric judge score and a numeric human score are treated as "the same call"
# when they land on the same side of this threshold.
BINARY_THRESHOLD = 0.5


def _scores_by_observation(
    lf, name: str, environment: str | None
) -> dict[str, tuple[float, str | None]]:
    """observation_id -> (value, comment) for one score name. Latest wins per observation."""
    out: dict[str, tuple[float, str | None]] = {}
    page = 1
    while True:
        kwargs: dict[str, object] = {"name": name, "page": page, "limit": 50}
        if environment:
            kwargs["environment"] = environment
        resp = lf.api.scores.get_many(**kwargs)
        if not resp.data:
            break
        for s in resp.data:
            obs_id = getattr(s, "observation_id", None)
            if obs_id is None or s.value is None:
                continue
            out[obs_id] = (float(s.value), getattr(s, "comment", None))
        if page >= resp.meta.total_pages:
            break
        page += 1
    return out


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


def _report(judge: dict, human: dict, environment: str | None) -> int:
    """Print the calibration point. Returns the number of paired observations."""
    scope = environment or "all environments"
    print(f"\nOBS7 judge/human calibration — {scope}\n" + "=" * 64)

    total_paired = 0
    for judge_name, (human_name, label, is_bool) in DIMENSIONS.items():
        j = judge.get(judge_name, {})
        h = human.get(human_name, {})
        paired = sorted(set(j) & set(h))
        total_paired += len(paired)

        print(f"\n{label}")
        print(f"  judge scores: {len(j):3d} ({judge_name})")
        print(f"  human scores: {len(h):3d} ({human_name})")
        print(f"  PAIRED:       {len(paired):3d}")

        if not paired:
            print("  -> no agreement computable: the two samples do not overlap.")
            continue

        agree = 0
        abs_errors: list[float] = []
        disagreements: list[tuple[str, float, float, str | None]] = []
        for obs_id in paired:
            jv, jc = j[obs_id]
            hv, _ = h[obs_id]
            abs_errors.append(abs(jv - hv))
            same = (
                (jv >= BINARY_THRESHOLD) == (hv >= BINARY_THRESHOLD)
                if not is_bool
                else bool(jv) == bool(hv)
            )
            if same:
                agree += 1
            else:
                disagreements.append((obs_id, jv, hv, jc))

        pct = 100.0 * agree / len(paired)
        mae = sum(abs_errors) / len(abs_errors)
        rule = "exact match" if is_bool else f"same side of {BINARY_THRESHOLD}"
        print(f"  agreement:    {agree}/{len(paired)} ({pct:.0f}%)  [{rule}]")
        if not is_bool:
            print(f"  mean abs err: {mae:.3f}")

        for obs_id, jv, hv, jc in disagreements:
            print(f"  DISAGREE {obs_id}: judge={jv} human={hv}")
            if jc:
                print(f"           judge said: {jc[:160]}")

    print("\n" + "=" * 64)
    if total_paired == 0:
        print(
            "NO CALIBRATION POINT YET — judges and humans have scored disjoint\n"
            "observations. Run with --queue-missing to queue the judge-scored\n"
            "observations for human annotation, then annotate them in the UI."
        )
    else:
        print(f"{total_paired} paired observation(s) across all dimensions.")
        if total_paired < 10:
            print(
                "⚠️  n is small: read this as a smoke-test of the pairing mechanism,\n"
                "    not as a calibration figure worth acting on."
            )
    return total_paired


def _queue_missing(lf, judge: dict, human: dict, dry_run: bool) -> None:
    """Queue judge-scored observations that no human has annotated yet."""
    judged: set[str] = set()
    for judge_name in DIMENSIONS:
        judged |= set(judge.get(judge_name, {}))
    annotated: set[str] = set()
    for _, (human_name, _, _) in DIMENSIONS.items():
        annotated |= set(human.get(human_name, {}))

    queue_id = _get_queue_id(lf, QUEUE_NAME)
    already = _existing_observation_ids(lf, queue_id)
    missing = sorted(judged - annotated - already)

    print(
        f"\njudge-scored observations: {len(judged)}; "
        f"already annotated: {len(judged & annotated)}; "
        f"already queued: {len(judged & already)}; to queue: {len(missing)}"
    )
    for obs_id in missing:
        if dry_run:
            print(f"  would queue observation {obs_id}")
            continue
        lf.api.annotation_queues.create_queue_item(
            queue_id, object_id=obs_id, object_type="OBSERVATION"
        )
        print(f"  queued observation {obs_id}")

    if missing and not dry_run:
        print(
            f"\n-> annotate these {len(missing)} item(s) in the {QUEUE_NAME!r} queue,\n"
            "   then re-run this script without --queue-missing to get the agreement."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environment",
        default=None,
        help="restrict to one Langfuse environment (e.g. production); default is all",
    )
    parser.add_argument(
        "--queue-missing",
        action="store_true",
        help="queue judge-scored observations that lack a human annotation",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="with --queue-missing: list, write nothing"
    )
    args = parser.parse_args()

    from langfuse import get_client

    lf = get_client()
    if not lf.auth_check():
        raise SystemExit("Langfuse client not authenticated — check LANGFUSE_* env vars")

    judge: dict[str, dict] = defaultdict(dict)
    human: dict[str, dict] = defaultdict(dict)
    for judge_name, (human_name, _, _) in DIMENSIONS.items():
        judge[judge_name] = _scores_by_observation(lf, judge_name, args.environment)
        human[human_name] = _scores_by_observation(lf, human_name, args.environment)

    _report(judge, human, args.environment)
    if args.queue_missing:
        _queue_missing(lf, judge, human, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
