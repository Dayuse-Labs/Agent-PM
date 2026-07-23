#!/usr/bin/env python3
"""eval_ranking.py — S-G9 (A8-a): first ranking-validity measurement, on
IDENTICAL candidates, to make "do we need a hotel reranker?" decidable.

Context (REVIEW-GEO-MULTITURN-AGENTB2C-2026-07-22.md, "Pertinence des hôtels
poussés" + plan §5 A8): AgentB2C has no reranker in response_bridge — it shows
the first `MAX_RESULTS` (5) hotels MCP_B2C returns for the resolved anchor.
The audit could not tell whether that is already near-optimal (MCP's own
order already tracks proximity) or whether a client-side reranker would
meaningfully improve relevance, because the harness dropped lat/lon/distance
from the record. S-G3/A8-a fixed the instrumentation (cards now carry
`latitude`/`longitude`/`distance_km`, `active_filters.distance_origin` carries
the anchor) — this script is the first thing to actually USE it.

Method (per audit §"Correctifs P0" item 8 and plan §8 "Ranking validated on
identical candidates"):
  1. Read an already-produced eval_pack.runner report (JSON) — this script
     NEVER calls /v3/chat itself, it only reads a report already produced by
     the gate replay (no extra live LLM calls).
  2. For each case's first turn that both returned hotels AND has a resolved
     anchor (`active_filters.distance_origin`) AND a resolved `date` (MCP
     requires one) — independently ask MCP_B2C `search_offers` for a page of
     up to 50 candidates around that SAME anchor/date/timeSlot/budget (an
     IDENTICAL candidate pool to the one the leaf's own call drew from), and
     compute true distance-from-anchor for every candidate (ground truth).
  3. Score AgentB2C's shown top-5 against that ground truth with
     precision@5 and NDCG@5 (relevance = 5..1 for true ranks 0..4, else 0).

Deliberate scope limits for this FIRST pass (documented, not silent):
  - Only the case's FIRST hotel-bearing turn is scored. A later "autres
    options" turn would need the internal pagination cursor (not exposed by
    the public /v3/chat contract) to build the matching ground-truth PAGE —
    reconstructing that isn't needed to answer "is a reranker needed" for the
    dominant first-page case, so it's left out rather than faked.
  - `hotelEquipmentIds` are only reconstructed for the amenity keys the leaf
    itself can express (`EQUIPMENT_IDS` below, kept as a static verbatim copy
    of `hotel_search_agent/equipment_ids.py`'s table so this script never has
    to import agents/** — same black-box discipline as S-G8's
    eval_hardening.py). An amenity outside that closed set can't appear
    (the leaf's own model-facing enum is closed to it), so this is exhaustive
    for what the leaf could have asked for, not an approximation.
  - MCP's own `score`/`matchReasons` fields (discovered live while building
    this script — not previously documented anywhere in this repo) blend
    review quality/tier signals, not just proximity. This script deliberately
    measures against DISTANCE ground truth only, per the audit's own spec
    ("vérité de distance") — it is not a verdict on whether MCP's score is
    "wrong", just a distance-relevance measurement, as asked.

Usage:
    python3 -u scripts/eval_ranking.py \\
        --report /path/to/replay_1.json \\
        --output /path/to/ranking_report.json
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import math
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# Verbatim copy of hotel_search_agent/equipment_ids.py::EQUIPMENT_IDS (read
# 2026-07-23) — kept static here rather than imported so this measurement
# script stays black-box (never imports agents/**), matching S-G8's
# eval_hardening.py discipline. Re-sync manually if that table ever changes.
EQUIPMENT_IDS: dict[str, tuple[int, ...]] = {
    "pool": (33, 34, 2982, 3000, 3001),
    "spa": (35,),
    "gym": (38,),
    "jacuzzi": (41,),
    "sauna": (2951,),
    "restaurant": (14,),
    "breakfast": (2992,),
    "pet_friendly": (2956,),
    "shuttle": (2949,),
}


def _load_dotenv() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _hour_window(start_hhmm: str | None, end_hhmm: str | None) -> tuple[int, int] | None:
    """Floor/ceil "HH:MM" strings to the integer-hour window MCP accepts —
    same floor/ceil semantics as hotel_search_agent/datetime_resolver.py's
    resolve_search_timeslot (verbatim re-derivation, not an import)."""
    if not start_hhmm or not end_hhmm:
        return None
    try:
        sh, sm = (int(p) for p in start_hhmm.split(":"))
        eh, em = (int(p) for p in end_hhmm.split(":"))
    except (ValueError, AttributeError):
        return None
    start_hour = sh
    end_hour = eh + (1 if em > 0 else 0)
    return max(0, min(23, start_hour)), max(0, min(23, end_hour))


def _exact_window(start_hhmm: str | None, end_hhmm: str | None) -> tuple[int, int] | None:
    """The two-sided EXACT minutes-of-day window — the leaf strict-filters its
    shown hotels against it (response_bridge._offer_fits_exact_window, S-G6),
    so the ground-truth pool must apply the same filter or nearer-but-
    non-fitting hotels would unfairly count as misses (S-G10, D5)."""
    if not start_hhmm or not end_hhmm:
        return None
    try:
        sh, sm = (int(p) for p in start_hhmm.split(":"))
        eh, em = (int(p) for p in end_hhmm.split(":"))
    except (ValueError, AttributeError):
        return None
    return sh * 60 + sm, eh * 60 + em


def _offer_minutes(offer: dict[str, Any], hour_key: str, minute_key: str) -> int | None:
    try:
        hour = int(offer.get(hour_key))  # type: ignore[arg-type]
        minute = int(offer.get(minute_key) or 0)
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def filter_pool_exact_window(
    pool: list[dict[str, Any]], window: tuple[int, int] | None
) -> list[dict[str, Any]]:
    """Mirror of the leaf's strict-then-fallback behavior (verbatim
    re-derivation of _offer_fits_exact_window + the A4-c fallback, never an
    agents/** import): keep hotels with at least one offer fitting ENTIRELY
    inside the exact window; if the strict cut empties a non-empty pool, fall
    back to the unfiltered pool — exactly what the leaf shows in that case."""
    if window is None:
        return pool
    start_total, end_total = window

    def _fits(offer: dict[str, Any]) -> bool:
        offer_start = _offer_minutes(offer, "startHour", "startMinute")
        if offer_start is None or offer_start < start_total:
            return False
        offer_end = _offer_minutes(offer, "endHour", "endMinute")
        return offer_end is not None and offer_end <= end_total

    strict = [
        h for h in pool
        if any(_fits(o) for o in (h.get("offers") or []) if isinstance(o, dict))
    ]
    return strict if strict else pool


def extract_samples(report: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """One sample per case: its FIRST turn with hotels + a resolved anchor +
    a resolved date. Returns (samples, skip_counts) — skips are counted, never
    silent (no-silent-cap discipline)."""
    samples: list[dict[str, Any]] = []
    skips: dict[str, int] = {
        "no_hotel_bearing_turn": 0,
        "no_anchor": 0,
        "no_date": 0,
        "no_shown_ids": 0,
    }
    for case in report.get("results", []):
        case_id = case.get("id")
        suite = case.get("suite")
        found = False
        for turn in case.get("turns", []):
            response = turn.get("response") or {}
            hotels = response.get("hotels") or []
            if not hotels:
                continue
            filters = response.get("active_filters") or {}
            anchor = filters.get("distance_origin") or {}
            lat, lon = anchor.get("latitude"), anchor.get("longitude")
            if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
                skips["no_anchor"] += 1
                found = True  # a hotel-bearing turn existed; just not usable
                break
            date = filters.get("date")
            if not date:
                skips["no_date"] += 1
                found = True
                break
            shown_ids = [h.get("id") for h in hotels if isinstance(h, dict) and h.get("id") is not None]
            if not shown_ids:
                skips["no_shown_ids"] += 1
                found = True
                break
            amenity_ids: list[int] = []
            for key in filters.get("amenities") or []:
                amenity_ids.extend(EQUIPMENT_IDS.get(key, ()))
            window = _hour_window(filters.get("timeslot_start"), filters.get("timeslot_end"))
            samples.append(
                {
                    "case_id": case_id,
                    "suite": suite,
                    "turn": turn.get("turn"),
                    "lat": float(lat),
                    "lon": float(lon),
                    "date": date,
                    "budget_max": filters.get("budget_max"),
                    "hotel_equipment_ids": sorted(set(amenity_ids)),
                    "time_window": window,
                    "exact_window": _exact_window(
                        filters.get("timeslot_start"), filters.get("timeslot_end")
                    ),
                    "shown_ids": shown_ids,
                }
            )
            found = True
            break
        if not found:
            skips["no_hotel_bearing_turn"] += 1
    return samples, skips


async def fetch_pool(session: Any, sample: dict[str, Any]) -> list[dict[str, Any]]:
    args: dict[str, Any] = {
        "lat": sample["lat"],
        "lon": sample["lon"],
        "date": sample["date"],
        "size": 50,
    }
    if sample["budget_max"]:
        args["priceRangeMax"] = float(sample["budget_max"])
    if sample["hotel_equipment_ids"]:
        args["hotelEquipmentIds"] = sample["hotel_equipment_ids"]
    if sample["time_window"]:
        args["timeSlot"] = {"startHour": sample["time_window"][0], "endHour": sample["time_window"][1]}
    result = await session.call_tool("search_offers", args)
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            data = json.loads(text)
            return [h for h in data.get("results", []) if isinstance(h, dict)]
    return []


def rank_by_distance(pool: list[dict[str, Any]], lat: float, lon: float) -> list[int]:
    scored = []
    for hotel in pool:
        hlat, hlon = hotel.get("lat"), hotel.get("lon")
        hid = hotel.get("hotelId")
        if isinstance(hlat, (int, float)) and isinstance(hlon, (int, float)) and hid is not None:
            scored.append((_haversine_km(lat, lon, hlat, hlon), hid))
    scored.sort(key=lambda t: t[0])
    return [hid for _, hid in scored]


def score_sample(shown_ids: list[Any], true_ranked_ids: list[Any]) -> dict[str, Any] | None:
    k = min(5, len(true_ranked_ids))
    if k == 0:
        return None
    true_top_k = true_ranked_ids[:k]
    rank_of = {hid: rank for rank, hid in enumerate(true_ranked_ids)}
    shown_top5 = shown_ids[:5]

    precision = len(set(shown_top5) & set(true_top_k)) / k

    def _rel(hid: Any) -> int:
        rank = rank_of.get(hid)
        return max(0, 5 - rank) if rank is not None else 0

    dcg = sum(_rel(hid) / math.log2(i + 2) for i, hid in enumerate(shown_top5))
    ideal_rels = [max(0, 5 - r) for r in range(k)]
    idcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(ideal_rels))
    ndcg = (dcg / idcg) if idcg > 0 else None

    return {
        "pool_size": len(true_ranked_ids),
        "precision_at_5": round(precision, 4),
        "ndcg_at_5": round(ndcg, 4) if ndcg is not None else None,
        "shown_top5": shown_top5,
        "true_top_k": true_top_k,
    }


async def run(report_path: Path, output_path: Path) -> dict[str, Any]:
    _load_dotenv()
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    report = json.loads(report_path.read_text(encoding="utf-8"))
    samples, skips = extract_samples(report)

    url = os.environ.get("MCP_B2C_URL", "")
    token = os.environ.get("MCP_B2C_AUTH_TOKEN", "").strip()
    if not url:
        raise SystemExit("MCP_B2C_URL not set — cannot fetch the ground-truth candidate pool")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    per_sample: list[dict[str, Any]] = []
    cache: dict[tuple, list[int]] = {}

    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for sample in samples:
                cache_key = (
                    round(sample["lat"], 4),
                    round(sample["lon"], 4),
                    sample["date"],
                    sample["time_window"],
                    sample["exact_window"],
                    tuple(sample["hotel_equipment_ids"]),
                    sample["budget_max"],
                )
                if cache_key not in cache:
                    pool = filter_pool_exact_window(
                        await fetch_pool(session, sample), sample["exact_window"]
                    )
                    cache[cache_key] = rank_by_distance(pool, sample["lat"], sample["lon"])
                true_ranked_ids = cache[cache_key]
                scored = score_sample(sample["shown_ids"], true_ranked_ids)
                per_sample.append(
                    {
                        "case_id": sample["case_id"],
                        "suite": sample["suite"],
                        "turn": sample["turn"],
                        **(scored or {"skipped": "empty_ground_truth_pool"}),
                    }
                )

    scored_rows = [row for row in per_sample if "skipped" not in row]
    precisions = [row["precision_at_5"] for row in scored_rows]
    ndcgs = [row["ndcg_at_5"] for row in scored_rows if row["ndcg_at_5"] is not None]

    by_suite: dict[str, dict[str, Any]] = {}
    for row in scored_rows:
        bucket = by_suite.setdefault(row["suite"], {"n": 0, "precisions": [], "ndcgs": []})
        bucket["n"] += 1
        bucket["precisions"].append(row["precision_at_5"])
        if row["ndcg_at_5"] is not None:
            bucket["ndcgs"].append(row["ndcg_at_5"])
    by_suite_summary = {
        suite: {
            "n": b["n"],
            "mean_precision_at_5": round(sum(b["precisions"]) / len(b["precisions"]), 4) if b["precisions"] else None,
            "mean_ndcg_at_5": round(sum(b["ndcgs"]) / len(b["ndcgs"]), 4) if b["ndcgs"] else None,
        }
        for suite, b in by_suite.items()
    }

    # Ground-truth pools are fetched NOW, not when the replay ran — inventory
    # drifts, and a past `date` makes MCP legitimately return a different (or
    # empty) pool. Disclose instead of letting a stale re-run read as signal.
    today = datetime.date.today().isoformat()
    n_past_date = sum(1 for s in samples if s["date"] < today)

    summary = {
        "n_samples_scored": len(scored_rows),
        "n_samples_skipped_empty_pool": len(per_sample) - len(scored_rows),
        "skip_counts_pre_pool": skips,
        "n_samples_with_past_date": n_past_date,
        "mean_precision_at_5": round(sum(precisions) / len(precisions), 4) if precisions else None,
        "mean_ndcg_at_5": round(sum(ndcgs) / len(ndcgs), 4) if ndcgs else None,
        "by_suite": by_suite_summary,
    }
    out = {
        "source_report": str(report_path),
        "ground_truth_fetched_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "samples": per_sample,
    }
    output_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", required=True, help="A run report already produced by eval_pack.runner")
    parser.add_argument("--output", required=True, help="Where to write the ranking report (never inside eval_pack/)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = asyncio.run(run(Path(args.report), Path(args.output)))
    s = result["summary"]
    print(
        f"ranking eval: {s['n_samples_scored']} sample(s) scored "
        f"(+{s['n_samples_skipped_empty_pool']} empty-pool, "
        f"skips pre-pool={s['skip_counts_pre_pool']}) — "
        f"mean precision@5={s['mean_precision_at_5']} mean NDCG@5={s['mean_ndcg_at_5']}"
    )
    if s["n_samples_with_past_date"]:
        print(
            f"  WARNING: {s['n_samples_with_past_date']} sample(s) have a past `date` — "
            "the ground-truth pool fetched today may not match the pool the replay drew "
            "from (re-run the gate replay fresh before trusting these numbers)"
        )
    for suite, row in s["by_suite"].items():
        print(f"  {suite}: n={row['n']} precision@5={row['mean_precision_at_5']} NDCG@5={row['mean_ndcg_at_5']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
