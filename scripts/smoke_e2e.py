#!/usr/bin/env python
"""Smoke e2e — real A2A turns through the running b2c-concierge (:8100).

Prerequisite: bash scripts/run_local.sh (boots concierge + the 2 leaves).

Default mode (S2 DoD): three INDEPENDENT turns, each must yield a NON-EMPTY
answer:
  1. ack    — deterministic template path, zero LLM: proves boot + bearer +
              spine wiring with no external dependency;
  2. search — routes to hotel-search-agent over A2A;
  3. faq    — routes to faq-agent over A2A.

`--conversation` (S06 DoD): four turns sharing the SAME A2A `contextId` —
ack, search, a bare "ok" follow-up, faq — proving the conversation stays
COHERENT across turns (same session, same profile continuity, S05/S06's
recovery-ack guard on the "ok" turn) rather than each call starting fresh.
The A2A executor derives both `session_id` and `user_id` from `contextId`
(google.adk.a2a.converters.request_converter) — passing the same one across
`message/send` calls is what continues the session.

Without credentials (.env: OPENAI_API_KEY, MCP_B2C_URL) the search/faq turns
exercise the HONEST DEGRADATION path (triage regex fallback + leaf failure →
a message that says so) — still non-empty by contract, never an invention.
With credentials they exercise the nominal LLM + MCP path.

No message content is logged beyond what this script itself sends (its own
test prompts, no real user data).
"""
from __future__ import annotations

import argparse
import datetime
import os
import sys
import time
import uuid

import httpx

CONCIERGE_URL = os.environ.get("CONCIERGE_URL", "http://localhost:8100/")
BEARER = os.environ.get("A2A_BEARER_TOKEN", "local-dev-token")
# triage (5 s) + leaf (10 s) + synthesis (15 s) + margin
TIMEOUT_SECONDS = float(os.environ.get("SMOKE_TIMEOUT_SECONDS", "60"))

# Explicit date: the leaf LLM has no clock, so a bare "demain" resolves to an
# arbitrary date until the S4 date-anchoring guard lands. The smoke pins it.
_TOMORROW = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

TURNS = [
    ("ack", "Bonjour !"),
    ("search", f"Je cherche un hôtel en journée à Paris le {_TOMORROW}"),
    ("faq", "Quelles sont les conditions d'annulation d'une réservation Dayuse ?"),
]

CONVERSATION_TURNS = [
    ("ack", "Bonjour !"),
    ("search", f"Je cherche un hôtel en journée à Paris le {_TOMORROW}"),
    ("recovery-ack", "ok"),
    ("faq", "Quelles sont les conditions d'annulation d'une réservation Dayuse ?"),
]


def _answer_text(result: dict) -> str:
    """Extract the answer text from an A2A message/send result (task or message),
    skipping thought-marked parts — same parsing as the fleet's spine legs."""
    parts: list[dict] = []
    for artifact in result.get("artifacts") or []:
        parts += artifact.get("parts") or []
    parts += ((result.get("status") or {}).get("message") or {}).get("parts") or []
    parts += result.get("parts") or []  # plain Message result
    texts = [
        p["text"]
        for p in parts
        if p.get("text") and not (p.get("metadata") or {}).get("adk_thought")
    ]
    return "\n".join(texts).strip()


def run_turn(client: httpx.Client, label: str, message: str, context_id: str | None = None) -> bool:
    req_id = f"smoke-{label}-{uuid.uuid4().hex[:8]}"
    message_payload = {
        "role": "user",
        "parts": [{"kind": "text", "text": message}],
        "messageId": req_id,
    }
    if context_id:
        message_payload["contextId"] = context_id
    t0 = time.monotonic()
    try:
        resp = client.post(
            CONCIERGE_URL,
            json={
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "message/send",
                "params": {"message": message_payload},
            },
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:  # noqa: BLE001 — a smoke failure must be printed, not raised
        print(f"FAIL  {label:<12} {type(exc).__name__}: {exc}")
        return False
    ms = int((time.monotonic() - t0) * 1000)
    if "error" in body:
        print(f"FAIL  {label:<12} JSON-RPC error: {body['error']} ({ms} ms)")
        return False
    result = body.get("result") or {}
    if context_id and result.get("contextId") != context_id:
        print(
            f"FAIL  {label:<12} contextId not honored: sent {context_id!r}, "
            f"got {result.get('contextId')!r} — the session did NOT continue ({ms} ms)"
        )
        return False
    answer = _answer_text(result)
    if not answer:
        print(f"FAIL  {label:<12} empty answer ({ms} ms)")
        return False
    preview = answer.replace("\n", " ")[:100]
    print(f"OK    {label:<12} {ms:>6} ms  {preview!r}")
    return True


def run_independent_turns(client: httpx.Client) -> bool:
    ok = True
    for label, message in TURNS:
        ok = run_turn(client, label, message) and ok
    return ok


def run_conversation(client: httpx.Client) -> bool:
    """S06 DoD: 4 turns, ONE shared contextId — proves the conversation stays
    coherent (same session/profile) rather than each call starting fresh."""
    context_id = str(uuid.uuid4())
    print(f"conversation contextId={context_id}")
    ok = True
    for label, message in CONVERSATION_TURNS:
        ok = run_turn(client, label, message, context_id=context_id) and ok
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--conversation",
        action="store_true",
        help="Run a 4-turn conversation sharing one A2A contextId instead of 3 independent turns.",
    )
    args = parser.parse_args()

    print(f"smoke_e2e → {CONCIERGE_URL}")
    with httpx.Client(
        timeout=TIMEOUT_SECONDS, headers={"Authorization": f"Bearer {BEARER}"}
    ) as client:
        ok = run_conversation(client) if args.conversation else run_independent_turns(client)
    print("smoke_e2e:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
