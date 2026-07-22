#!/usr/bin/env python
"""run_judge_ab.py — S-D of the agent-usa vs AgentB2C comparative audit.

HTTP-replays `evalset/evalset-v0.json` (32 scenarios, 8 families) against ONE
arbitrary `/v3/chat` endpoint and scores each scenario's final answer with the
existing LLM-as-judge (`evals/judge.py::LLMJudge`) — the SAME rubric the S08
in-process battery (`evals/battery.py`) uses, but driven black-box over HTTP so
the identical script judges either stack (agent-usa OR the AgentB2C
candidate). Run once per agent; diff the two output reports by hand for the
"quality" section of `AUDIT-COMPARATIF-AB-2026-07.md` (S-F).

Wire protocol mirrors `dayuse_eval_pack/eval_pack/runner.py::HttpChatClient`
(a sibling deliverable of this same comparative-audit toolset, not importable
from here — this branch predates its PR #18 merge): stdlib `urllib.request`
(no new dependency), session continuity via the BODY field `session_id`
(not the `X-Client-Session-Id` header — body-field works against both the
AgentB2C façade, which honors it in phase M1, AND agent-usa's own endpoint),
one id per SCENARIO shaped `canonical-eval-<scenario_id>-<8 hex>` (same
`canonical-eval-` prefix already documented as a recognized-synthetic session
prefix). Every request also carries `X-Dayuse-Synthetic: 1` — this traffic is
synthetic no matter which stack receives it, not just when going through the
AgentB2C-specific eval-pack adapter.

Per-turn LLM-call budget is NOT measured here — that needs in-process access
to the concierge's own metric log (`evals/battery.py`'s job); agent-usa has no
equivalent instrumentation at all. This script judges QUALITY only.

Usage:
  python scripts/run_judge_ab.py --endpoint http://127.0.0.1:8100/v3/chat \\
      --label candidate --out reports/judge_candidate.json
  python scripts/run_judge_ab.py --endpoint http://127.0.0.1:5002/v3/chat \\
      --label agent_usa --api-key "$CHAT_API_KEY" --out reports/judge_agent_usa.json
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_EVALSET_PATH = REPO_ROOT / "evalset" / "evalset-v0.json"


def _load_dotenv() -> None:
    """Minimal .env loader (KEY=VALUE lines) — only sets keys absent from the
    environment, so `source .env` / real env always win. Same hand-rolled
    pattern every script in this repo already uses (no python-dotenv dep)."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class TurnResult:
    user: str
    answer: str
    http_status: int | None
    latency_ms: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "user": self.user,
            "answer": self.answer,
            "http_status": self.http_status,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


class HttpChatClient:
    """POSTs `{"session_id", "message"}` to one `/v3/chat`-shaped endpoint.
    Never raises: a transport error or non-2xx status becomes a dict with
    `_http_status`/`_http_error` set instead — mirrors
    `dayuse_eval_pack/eval_pack/runner.py::HttpChatClient`'s degrade-never-raise
    contract, so callers never need a try/except around `.send()`."""

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str = "",
        timeout: float = 60.0,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout = timeout
        self.extra_headers = dict(extra_headers or {})

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            # GDPR hygiene invariant of this audit toolset: every request this
            # script sends is synthetic traffic, regardless of which stack
            # receives it — never rely on an intermediary (e.g. the eval-pack
            # adapter) to add this.
            "X-Dayuse-Synthetic": "1",
            **self.extra_headers,
        }
        if self.api_key:
            headers["X-Internal-Api-Key"] = self.api_key
        return headers

    def send(self, *, session_id: str, message: str) -> dict[str, Any]:
        payload = {"session_id": session_id, "message": message}
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                body = response.read().decode("utf-8")
                parsed = json.loads(body) if body else {}
                parsed["_http_status"] = response.status
                return parsed
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body) if body else {}
            except json.JSONDecodeError:
                parsed = {"_raw": body[:2000]}
            parsed["_http_status"] = exc.code
            parsed["_http_error"] = str(exc)
            return parsed
        except Exception as exc:  # noqa: BLE001 — connection failure, timeout, etc.
            return {"_http_status": None, "_http_error": f"{type(exc).__name__}: {exc}"}

    def probe(self, *, timeout: float = 5.0) -> tuple[bool, str]:
        """One throwaway send(). True on ANY HTTP response (even 4xx/5xx —
        that still proves the server is up); False only on a connection-level
        failure (refused/timeout/DNS), so the caller can bail BEFORE spending
        judge-LLM calls against a dead endpoint."""
        saved_timeout = self.timeout
        self.timeout = timeout
        try:
            result = self.send(session_id=f"canonical-eval-probe-{uuid.uuid4().hex[:8]}", message="ping")
        finally:
            self.timeout = saved_timeout
        status = result.get("_http_status")
        if status is None:
            return False, result.get("_http_error", "connection failed")
        return True, f"http {status}"


def session_id_for(scenario_id: str) -> str:
    """One id per scenario, reused across all its turns. Same
    `canonical-eval-` prefix convention as the eval-pack runner."""
    return f"canonical-eval-{scenario_id[:40]}-{uuid.uuid4().hex[:8]}"


def replay_scenario(
    scenario: dict[str, Any], *, client: HttpChatClient, pause_ms: int = 0
) -> dict[str, Any]:
    """Replays `scenario['user_turns']` sequentially against `client`, ONE
    session id for the whole scenario. A turn's HTTP failure yields an empty
    answer for that turn — it never aborts the rest of the scenario, so a
    single flaky turn doesn't lose an otherwise-judgeable transcript."""
    session_id = session_id_for(str(scenario["id"]))
    turns: list[dict[str, Any]] = []
    for user_turn in scenario["user_turns"]:
        started = time.perf_counter()
        response = client.send(session_id=session_id, message=user_turn)
        latency_ms = (time.perf_counter() - started) * 1000
        answer = str(response.get("message") or "")
        turns.append(
            TurnResult(
                user=user_turn,
                answer=answer,
                http_status=response.get("_http_status"),
                latency_ms=round(latency_ms, 2),
                error=response.get("_http_error"),
            ).to_dict()
        )
        if pause_ms:
            time.sleep(pause_ms / 1000)
    return {
        "scenario_id": scenario["id"],
        "family": scenario["family"],
        "lang": scenario.get("lang", "fr"),
        "turns": turns,
    }


async def judge_scenario(
    replay: dict[str, Any], scenario: dict[str, Any], *, judge: Any
) -> dict[str, Any]:
    """Scores `replay`'s answers against `scenario['expected']` with ONE
    `judge.evaluate(...)` call. `judge` is duck-typed (anything with an async
    `.evaluate(**kwargs) -> Judgment`-shaped object with `.to_dict()`) so tests
    can inject a fake without touching litellm."""
    answers = [t["answer"] for t in replay["turns"]]
    judgment = await judge.evaluate(
        scenario_id=replay["scenario_id"],
        family=replay["family"],
        lang=replay["lang"],
        user_turns=scenario["user_turns"],
        answers=answers,
        expected=scenario.get("expected", ""),
    )
    return {**replay, "judgment": judgment.to_dict()}


async def run_judge_ab(
    scenarios: list[dict[str, Any]],
    *,
    client: HttpChatClient,
    judge: Any = None,
    pause_ms: int = 0,
    progress: bool = False,
) -> dict[str, Any]:
    """Sequential, not parallel — courtesy to a real server under test (and
    respects `pause_ms`), mirrors the eval-pack runner's own throttling."""
    from evals.judge import LLMJudge

    judge = judge or LLMJudge()
    results: list[dict[str, Any]] = []
    for i, scenario in enumerate(scenarios, 1):
        replay = replay_scenario(scenario, client=client, pause_ms=pause_ms)
        result = await judge_scenario(replay, scenario, judge=judge)
        results.append(result)
        if progress:
            j = result["judgment"]
            print(
                f"  [{i}/{len(scenarios)}] {result['family']:<16} {result['scenario_id']:<22} "
                f"{j['verdict']:<5} score={j['score']:.0f}",
                flush=True,
            )
    return {"summary": summarize_judge_ab(results), "results": results}


def run_judge_ab_sync(
    scenarios: list[dict[str, Any]],
    *,
    client: HttpChatClient,
    judge: Any = None,
    pause_ms: int = 0,
    progress: bool = False,
) -> dict[str, Any]:
    return asyncio.run(
        run_judge_ab(scenarios, client=client, judge=judge, pause_ms=pause_ms, progress=progress)
    )


def summarize_judge_ab(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-family (canonical `FAMILY_ORDER`, reused from `evals.battery` for
    ordering only) + "overall": passed/total/pass_rate, mean_score. NOT
    `evals.battery.summarize()` — that shape assumes a per-turn LLM-call
    budget (`over_budget`/`max_llm_calls`) this black-box HTTP script cannot
    measure for either stack; faking those fields as zero would misrepresent
    unmeasured data as measured."""
    from evals.battery import FAMILY_ORDER

    def _stats(group: list[dict[str, Any]]) -> dict[str, Any]:
        count = len(group)
        if count == 0:
            return {"count": 0, "passed": 0, "pass_rate": 0.0, "mean_score": 0.0}
        passed = sum(1 for r in group if r["judgment"]["verdict"] == "pass")
        mean_score = sum(r["judgment"]["score"] for r in group) / count
        return {
            "count": count,
            "passed": passed,
            "pass_rate": round(passed / count, 3),
            "mean_score": round(mean_score, 3),
        }

    by_family: dict[str, Any] = {}
    for fam in FAMILY_ORDER:
        group = [r for r in results if r["family"] == fam]
        if group:
            by_family[fam] = _stats(group)
    for r in results:
        if r["family"] not in by_family and r["family"] not in FAMILY_ORDER:
            by_family.setdefault(r["family"], _stats([r for x in [r] for r in [r]]))

    return {"total": len(results), "overall": _stats(results), "by_family": by_family}


def build_report(
    summary: dict[str, Any],
    results: list[dict[str, Any]],
    *,
    endpoint: str,
    judge_model: str,
    generated_at: str,
    label: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": "judge-ab-v0",
        "generated_at": generated_at,
        "label": label,
        "endpoint": endpoint,
        "judge_model": judge_model,
        "summary": summary,
        "results": results,
    }


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--endpoint", required=True, help="Full /v3/chat URL, e.g. http://127.0.0.1:8100/v3/chat")
    parser.add_argument("--evalset-path", default=str(DEFAULT_EVALSET_PATH))
    parser.add_argument("--families", default="", help="Comma-separated family filter (default: all 8).")
    parser.add_argument("--limit", type=int, default=None, help="Max scenarios per family.")
    parser.add_argument("--out", default=str(REPO_ROOT / "reports" / "judge_ab.json"))
    parser.add_argument("--api-key", default=os.environ.get("CHAT_API_KEY", ""))
    parser.add_argument("--judge-model", default="")
    parser.add_argument("--pause-ms", type=int, default=300)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--label", default="")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    _load_dotenv()
    if args.judge_model:
        os.environ["RELEASE_GATE_JUDGE_MODEL"] = args.judge_model

    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "run_judge_ab: OPENAI_API_KEY not set — the judge pass needs it. Aborting.",
            file=sys.stderr,
        )
        return 2

    from evals.battery import load_scenarios

    families = [f.strip() for f in args.families.split(",") if f.strip()] or None
    scenarios = load_scenarios(Path(args.evalset_path), families=families, limit=args.limit)
    if not scenarios:
        print("run_judge_ab: no scenarios matched the filter.", file=sys.stderr)
        return 2

    client = HttpChatClient(endpoint=args.endpoint, api_key=args.api_key, timeout=args.timeout)
    reachable, reason = client.probe()
    if not reachable:
        print(f"run_judge_ab: endpoint unreachable ({reason}) — {args.endpoint}. Aborting.", file=sys.stderr)
        return 2

    judge_model = os.environ.get("RELEASE_GATE_JUDGE_MODEL", os.environ.get("DAYUSE_MODEL", "gpt-4o-mini"))
    print(
        f"judge-ab → {len(scenarios)} scenario(s) against {args.endpoint} "
        f"(label={args.label or '(none)'}, judge={judge_model})",
        flush=True,
    )
    report_core = run_judge_ab_sync(
        scenarios, client=client, pause_ms=args.pause_ms, progress=not args.quiet
    )
    report = build_report(
        report_core["summary"],
        report_core["results"],
        endpoint=args.endpoint,
        judge_model=judge_model,
        generated_at=_now_iso(),
        label=args.label,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = report["summary"]
    print(f"\n{'=' * 56}")
    print(f"judge-ab: {summary['overall']['passed']}/{summary['total']} passed (mean score {summary['overall']['mean_score']})")
    print("per-family:")
    for fam, stat in summary["by_family"].items():
        print(f"  {fam:<18} {stat['passed']}/{stat['count']}  ({stat['pass_rate']:.0%}, mean {stat['mean_score']})")
    print(f"report → {out_path}")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    sys.exit(main())
