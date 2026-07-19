#!/usr/bin/env python
"""measure_ttft_local.py — S06 DoD: local TTFT (time-to-first `progress`
event), no network / no API key required.

`agent.py`'s `_run_async_impl` yields the internal `progress` marker event
BEFORE any awaited work at all (before loading the session profile, before
triage) — this script measures wall-clock from just before the turn starts to
that first yielded event, which is exactly the SSE facade's future TTFT (S9
exposes it over the wire; here it is measured directly on the internal ADK
event stream). No LLM/leaf call ever needs to complete for this measurement:
the async generator is closed right after its first event.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agents" / "b2c_concierge"))

from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types as genai_types  # noqa: E402

from b2c_concierge.agent import root_agent  # noqa: E402

TARGET_MS = float(os.environ.get("CONCIERGE_TTFT_TARGET_MS", "300"))


async def _measure() -> float:
    runner = InMemoryRunner(root_agent)
    session = await runner.session_service.create_session(app_name=runner.app_name, user_id="ttft")
    content = genai_types.Content(
        role="user", parts=[genai_types.Part(text="je cherche un hôtel à Paris demain")]
    )
    t0 = time.monotonic()
    agen = runner.run_async(user_id="ttft", session_id=session.id, new_message=content)
    try:
        first_event = await agen.__anext__()
    finally:
        await agen.aclose()
    ms = (time.monotonic() - t0) * 1000
    if not first_event.partial:
        raise AssertionError("the first event must be the internal progress marker (partial=True)")
    return ms


def main() -> int:
    ms = asyncio.run(_measure())
    print(f"TTFT (first progress event): {ms:.1f} ms (target < {TARGET_MS:.0f} ms)")
    if ms >= TARGET_MS:
        print("FAIL: progress event too slow")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
