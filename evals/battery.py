"""Conversational battery harness for the b2c-concierge (S08).

Replays the fixed 32-scenario evalset (`evalset/evalset-v0.json`, 8 families x 4)
against the orchestrator and judges each scenario, family by family.

Adaptation of agent-usa's `run_dynamic_conversation_regression.py`, with three
deliberate departures documented in the S08 HANDOFF block:

- **Fixed scenarios, not generated.** agent-usa generates randomized variants
  around fragile families (needs a seed); our evalset is the committed 32-case
  set from Phase 0, so we replay it verbatim (reproducible, no seed).
- **In-process driving, not black-box HTTP.** We drive `root_agent` through a
  real `InMemoryRunner` (the `measure_ttft_local.py` pattern) rather than POSTing
  to a running service. Rationale: the public HTTP `/v3/chat`+SSE facade is S9's
  zone (OUT of scope here); the spine behaviour under test is identical either
  way; and driving in-process lets us read the per-turn LLM-call budget straight
  from the concierge's own metric log (no cross-process log scraping) and give
  each scenario real profile continuity via an injected in-memory store.
- **Per-turn LLM-budget assertion.** agent-usa's battery does not measure the
  per-turn call count; ours does — the S02 `concierge_metric=turn ... llm_calls=N`
  line is captured per turn and any turn over the cap (3) is ship-blocking.

Profile continuity uses an injected fakeredis-backed `ProfileStore`: deterministic,
self-contained (no Redis server needed), and correctly orchestrator-only — the
stateless leaves keep their own contract. "Live" here means real LLM calls
(triage / synthesis / judge), not "over the network".
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .judge import LLMJudge, Judgment

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALSET_PATH = REPO_ROOT / "evalset" / "evalset-v0.json"

# Mirrors b2c_concierge.budget.MAX_LLM_CALLS_PER_TURN (the CLAUDE.md invariant
# "<= 3 appels LLM/tour"); kept as a literal so this module imports with no
# dependency on the agent package for the offline unit tests of its helpers.
MAX_LLM_CALLS_PER_TURN = 3

# Canonical family order (phase S08 step 2).
FAMILY_ORDER = (
    "simple_search",
    "empty_dead",
    "empty_recovered",
    "budget_search",
    "timeslot_search",
    "named_hotel",
    "compare",
    "multi_turn_long",
)


# --- Scenario loading -----------------------------------------------------------------------
def load_scenarios(
    path: Path | None = None,
    families: list[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Load scenarios from the evalset, optionally filtered to `families` and
    capped to `limit` per family. Returned in canonical family order (phase
    step 2), stable within a family."""
    data = json.loads((path or EVALSET_PATH).read_text(encoding="utf-8"))
    scenarios: list[dict[str, Any]] = data["scenarios"]
    wanted = set(families) if families else None

    per_family: dict[str, list[dict[str, Any]]] = OrderedDict()
    for fam in FAMILY_ORDER:
        per_family[fam] = []
    for sc in scenarios:
        fam = sc.get("family", "")
        if wanted is not None and fam not in wanted:
            continue
        per_family.setdefault(fam, []).append(sc)

    ordered: list[dict[str, Any]] = []
    for fam, group in per_family.items():
        ordered.extend(group[:limit] if limit else group)
    return ordered


# --- Per-turn budget capture ----------------------------------------------------------------
_TURN_METRIC_RE = re.compile(
    r"concierge_metric=turn\s+family=(?P<family>\S+)\s+route=(?P<route>\S+)\s+"
    r"llm_calls=(?P<llm_calls>\d+)\s+phases=(?P<phases>\S+)\s+ms=(?P<ms>\d+)\s+"
    r"status=(?P<status>\S+)"
)


def parse_turn_metric(message: str) -> dict[str, Any] | None:
    """Parse one `concierge_metric=turn ...` log line into a dict, or None if it
    is not a turn metric line. Pure — unit-tested offline."""
    m = _TURN_METRIC_RE.search(message)
    if not m:
        return None
    return {
        "family": m.group("family"),
        "route": m.group("route"),
        "llm_calls": int(m.group("llm_calls")),
        "phases": m.group("phases"),
        "ms": int(m.group("ms")),
        "status": m.group("status"),
    }


class TurnMetricHandler(logging.Handler):
    """Captures the concierge's per-turn metric lines as they are emitted. Turns
    are driven sequentially, so `drain()` after a turn yields exactly the metric
    line(s) that turn produced (normally one)."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        parsed = parse_turn_metric(record.getMessage())
        if parsed is not None:
            self.records.append(parsed)

    def drain(self) -> list[dict[str, Any]]:
        out = self.records[:]
        self.records.clear()
        return out


# --- In-process driving ---------------------------------------------------------------------
def _ensure_agent_importable() -> None:
    pkg_dir = str(REPO_ROOT / "agents" / "b2c_concierge")
    if pkg_dir not in sys.path:
        sys.path.insert(0, pkg_dir)


def _install_fake_profile_store() -> None:
    """Inject a fakeredis-backed ProfileStore so each scenario gets real profile
    continuity across its turns without a Redis server (deterministic, offline).
    Orchestrator-only by construction — the leaves stay stateless."""
    import fakeredis.aioredis

    import b2c_concierge.agent as agent_module
    from b2c_concierge.profile_store import ProfileStore

    store = ProfileStore(fakeredis.aioredis.FakeRedis(decode_responses=True))
    agent_module.get_profile_store = lambda: store  # type: ignore[assignment]


def _answer_text(events: list) -> str:
    """The final answer = the terminal NON-partial event(s) (S06: progress /
    hotels markers and streamed chunks are all partial and excluded)."""
    texts = [
        part.text
        for event in events
        if not event.partial and event.content and event.content.parts
        for part in event.content.parts
        if part.text
    ]
    return "\n".join(texts).strip()


async def _drive_scenario(
    scenario: dict[str, Any], handler: TurnMetricHandler
) -> list[dict[str, Any]]:
    """Replay one scenario's user_turns in a single fresh ADK session (turns
    share continuity); returns a per-turn list of {user, answer, + budget}."""
    from google.adk.runners import InMemoryRunner
    from google.genai import types as genai_types

    import b2c_concierge.agent as agent_module

    runner = InMemoryRunner(agent_module.root_agent)
    session = await runner.session_service.create_session(
        app_name=runner.app_name, user_id=f"battery-{scenario['id']}"
    )
    turns: list[dict[str, Any]] = []
    for user_turn in scenario["user_turns"]:
        content = genai_types.Content(role="user", parts=[genai_types.Part(text=user_turn)])
        handler.drain()  # discard anything stale before this turn
        events = [
            e
            async for e in runner.run_async(
                user_id=session.user_id, session_id=session.id, new_message=content
            )
        ]
        metrics = handler.drain()
        metric = metrics[-1] if metrics else {}
        turns.append(
            {
                "user": user_turn,
                "answer": _answer_text(events),
                "llm_calls": metric.get("llm_calls"),
                "phases": metric.get("phases"),
                "route": metric.get("route"),
                "status": metric.get("status"),
            }
        )
    return turns


# --- Battery run ----------------------------------------------------------------------------
async def run_battery(
    scenarios: list[dict[str, Any]],
    judge: LLMJudge | None = None,
    *,
    progress: bool = False,
) -> dict[str, Any]:
    """Drive + judge every scenario in-process. Returns a results dict with a
    per-family summary and a per-turn budget accounting."""
    _ensure_agent_importable()
    _install_fake_profile_store()
    judge = judge or LLMJudge()

    metrics_logger = logging.getLogger("b2c_concierge.metrics")
    handler = TurnMetricHandler()
    metrics_logger.addHandler(handler)
    results: list[dict[str, Any]] = []
    try:
        for i, sc in enumerate(scenarios, 1):
            turns = await _drive_scenario(sc, handler)
            answers = [t["answer"] for t in turns]
            judgment = await judge.evaluate(
                scenario_id=sc["id"],
                family=sc["family"],
                lang=sc.get("lang", "fr"),
                user_turns=sc["user_turns"],
                answers=answers,
                expected=sc.get("expected", ""),
            )
            results.append(_scenario_result(sc, turns, judgment))
            if progress:
                over = " OVER-BUDGET" if results[-1]["over_budget"] else ""
                print(
                    f"  [{i}/{len(scenarios)}] {sc['family']:<16} {sc['id']:<22} "
                    f"{judgment.verdict:<5} score={judgment.score:.0f}{over}",
                    flush=True,
                )
    finally:
        metrics_logger.removeHandler(handler)

    return {"summary": summarize(results), "results": results}


def _scenario_result(
    scenario: dict[str, Any], turns: list[dict[str, Any]], judgment: Judgment
) -> dict[str, Any]:
    observed = [t["llm_calls"] for t in turns if t["llm_calls"] is not None]
    max_calls = max(observed) if observed else 0
    return {
        **judgment.to_dict(),
        "lang": scenario.get("lang", "fr"),
        "turns": turns,
        "max_llm_calls": max_calls,
        "over_budget": max_calls > MAX_LLM_CALLS_PER_TURN,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate pass counts per family + the budget accounting. Pure —
    unit-tested offline."""
    total = len(results)
    passed = sum(1 for r in results if r["verdict"] == "pass")
    over_budget_turns = sum(1 for r in results if r["over_budget"])
    max_observed = max((r["max_llm_calls"] for r in results), default=0)

    by_family: dict[str, dict[str, Any]] = OrderedDict()
    for fam in FAMILY_ORDER:
        group = [r for r in results if r["family"] == fam]
        if not group:
            continue
        fam_passed = sum(1 for r in group if r["verdict"] == "pass")
        by_family[fam] = {
            "passed": fam_passed,
            "count": len(group),
            "pass_rate": round(fam_passed / len(group), 3),
        }
    # families outside the canonical order (defensive — shouldn't happen)
    for r in results:
        if r["family"] not in by_family and r["family"] not in FAMILY_ORDER:
            by_family.setdefault(r["family"], {"passed": 0, "count": 0, "pass_rate": 0.0})

    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "max_llm_calls_per_turn_observed": max_observed,
        "over_budget_turns": over_budget_turns,
        "by_family": by_family,
    }


def run_battery_sync(
    scenarios: list[dict[str, Any]], judge: LLMJudge | None = None, *, progress: bool = False
) -> dict[str, Any]:
    return asyncio.run(run_battery(scenarios, judge, progress=progress))
