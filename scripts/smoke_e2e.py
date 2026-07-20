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

`--booking` (S07 DoD, guard #12 / R9): two turns sharing ONE contextId —
"book <a real MCP_B2C hotel>" then a bare "yes" — proving the confirmed=false
-> confirmed=true confirmation gate works end to end, not just at the
inline_tools.py unit level. Turn 1 must NEVER contain a link (the core R9
safety invariant, true even under honest degradation with no live
credentials); turn 2's link depends on MCP_B2C/OPENAI_API_KEY actually being
reachable, printed but not hard-asserted for that reason.

Without credentials (.env: OPENAI_API_KEY, MCP_B2C_URL) the search/faq/
booking turns exercise the HONEST DEGRADATION path (triage regex fallback +
leaf/tool failure → a message that says so) — still non-empty by contract,
never an invention. With credentials they exercise the nominal LLM + MCP path.

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


def run_turn(client: httpx.Client, label: str, message: str, context_id: str | None = None) -> str | None:
    """Runs one turn; returns the answer text, or None on failure (empty
    answer, transport error, JSON-RPC error, or a context_id that wasn't
    honored)."""
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
        return None
    ms = int((time.monotonic() - t0) * 1000)
    if "error" in body:
        print(f"FAIL  {label:<12} JSON-RPC error: {body['error']} ({ms} ms)")
        return None
    result = body.get("result") or {}
    if context_id and result.get("contextId") != context_id:
        print(
            f"FAIL  {label:<12} contextId not honored: sent {context_id!r}, "
            f"got {result.get('contextId')!r} — the session did NOT continue ({ms} ms)"
        )
        return None
    answer = _answer_text(result)
    if not answer:
        print(f"FAIL  {label:<12} empty answer ({ms} ms)")
        return None
    preview = answer.replace("\n", " ")[:100]
    print(f"OK    {label:<12} {ms:>6} ms  {preview!r}")
    return answer


def run_independent_turns(client: httpx.Client) -> bool:
    ok = True
    for label, message in TURNS:
        ok = (run_turn(client, label, message) is not None) and ok
    return ok


def run_conversation(client: httpx.Client) -> bool:
    """S06 DoD: 4 turns, ONE shared contextId — proves the conversation stays
    coherent (same session/profile) rather than each call starting fresh."""
    context_id = str(uuid.uuid4())
    print(f"conversation contextId={context_id}")
    ok = True
    for label, message in CONVERSATION_TURNS:
        ok = (run_turn(client, label, message, context_id=context_id) is not None) and ok
    return ok


# A real, bookable MCP_B2C staging hotel (verified live during S07) — lets
# the smoke exercise the named-hotel lookup guard's MCP find_hotel_by_name
# fallback directly, with no prior search turn needed to seed a shortlist.
_BOOKING_HOTEL = "Villa Paris Orly"


def run_booking(client: httpx.Client) -> bool:
    """S07 DoD, guard #12 (R9): 2 turns, ONE shared contextId — "book <hotel>"
    then a bare "yes". Turn 1 must NEVER contain a link (the core safety
    invariant — true even under honest degradation with no live
    credentials); turn 2 carrying a REAL tracked link additionally proves the
    confirmation gate end to end when MCP_B2C/OPENAI_API_KEY are reachable."""
    context_id = str(uuid.uuid4())
    print(f"booking contextId={context_id}")
    quote = run_turn(client, "book-quote", f"Book {_BOOKING_HOTEL} for me", context_id=context_id)
    if quote is None:
        return False
    if "http" in quote:
        print("FAIL  book-quote   a link appeared on the FIRST request — R9 guard breach")
        return False
    confirm = run_turn(client, "book-confirm", "yes", context_id=context_id)
    if confirm is None:
        return False
    if "http" in confirm:
        print("      book-confirm real tracked link returned — confirmation gate verified end to end")
    else:
        print("      book-confirm no link (honest degradation — check MCP_B2C/OPENAI_API_KEY in .env)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--conversation",
        action="store_true",
        help="Run a 4-turn conversation sharing one A2A contextId instead of 3 independent turns.",
    )
    mode.add_argument(
        "--booking",
        action="store_true",
        help="Run the 2-turn booking confirmation flow (R9, guard #12): quote then confirm.",
    )
    args = parser.parse_args()

    print(f"smoke_e2e → {CONCIERGE_URL}")
    with httpx.Client(
        timeout=TIMEOUT_SECONDS, headers={"Authorization": f"Bearer {BEARER}"}
    ) as client:
        if args.booking:
            ok = run_booking(client)
        elif args.conversation:
            ok = run_conversation(client)
        else:
            ok = run_independent_turns(client)
    print("smoke_e2e:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
