#!/usr/bin/env python
"""Smoke e2e — S2 DoD: real A2A turns through the running b2c-concierge (:8100).

Prerequisite: bash scripts/run_local.sh (boots concierge + the 2 leaves).

Three turns, each must yield a NON-EMPTY answer:
  1. ack    — deterministic template path, zero LLM: proves boot + bearer +
              spine wiring with no external dependency;
  2. search — routes to hotel-search-agent over A2A;
  3. faq    — routes to faq-agent over A2A.

Without credentials (.env: OPENAI_API_KEY, MCP_B2C_URL) the search/faq turns
exercise the HONEST DEGRADATION path (triage regex fallback + leaf failure →
a message that says so) — still non-empty by contract, never an invention.
With credentials they exercise the nominal LLM + MCP path.

No message content is logged beyond what this script itself sends (its own
test prompts, no real user data).
"""
from __future__ import annotations

import os
import sys
import time
import uuid

import httpx

CONCIERGE_URL = os.environ.get("CONCIERGE_URL", "http://localhost:8100/")
BEARER = os.environ.get("A2A_BEARER_TOKEN", "local-dev-token")
# triage (5 s) + leaf (10 s) + synthesis (15 s) + margin
TIMEOUT_SECONDS = float(os.environ.get("SMOKE_TIMEOUT_SECONDS", "60"))

TURNS = [
    ("ack", "Bonjour !"),
    ("search", "Je cherche un hôtel en journée à Paris demain"),
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


def run_turn(client: httpx.Client, label: str, message: str) -> bool:
    req_id = f"smoke-{label}-{uuid.uuid4().hex[:8]}"
    t0 = time.monotonic()
    try:
        resp = client.post(
            CONCIERGE_URL,
            json={
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [{"kind": "text", "text": message}],
                        "messageId": req_id,
                    },
                },
            },
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:  # noqa: BLE001 — a smoke failure must be printed, not raised
        print(f"FAIL  {label:<7} {type(exc).__name__}: {exc}")
        return False
    ms = int((time.monotonic() - t0) * 1000)
    if "error" in body:
        print(f"FAIL  {label:<7} JSON-RPC error: {body['error']} ({ms} ms)")
        return False
    answer = _answer_text(body.get("result") or {})
    if not answer:
        print(f"FAIL  {label:<7} empty answer ({ms} ms)")
        return False
    preview = answer.replace("\n", " ")[:100]
    print(f"OK    {label:<7} {ms:>6} ms  {preview!r}")
    return True


def main() -> int:
    print(f"smoke_e2e → {CONCIERGE_URL}")
    ok = True
    with httpx.Client(
        timeout=TIMEOUT_SECONDS, headers={"Authorization": f"Bearer {BEARER}"}
    ) as client:
        for label, message in TURNS:
            ok = run_turn(client, label, message) and ok
    print("smoke_e2e:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
