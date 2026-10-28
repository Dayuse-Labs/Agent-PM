#!/usr/bin/env python3
"""R1 (review of #173): does the search leaf's model set `amenities_must_have`
when the amenity IS the request, and not when it is a plus?

The zero-result rescue (`relaxation.py`) drops an amenity first, unless the
model marked it `amenities_must_have`: « je veux un après-midi spa » must keep
its spa (the ring widens instead), « near the airport, ideally with a pool »
may lose its pool. The unit tests stub the flag; this runs the REAL leaf
(`root_agent`, its model and prompt) on `evals/amenities_must_have_inputs.jsonl`
and reads the `search_offers` call the model writes (before any callback pops
the virtual params). Its tools run for real (Mapbox, MCP_B2C read-only): run it
with the hotel-search service's environment, e.g.

    railway run -s hotel-search -- env -u LANGFUSE_PUBLIC_KEY -u LANGFUSE_SECRET_KEY \\
      PYTHONPATH=agents/hotel_search_agent DISABLE_AIOHTTP_TRANSPORT=True \\
      .venv/bin/python scripts/measure_amenities_must_have.py --runs 3

A « goal » input passes when the call carries an amenity and
`amenities_must_have: true`; a « plus » input passes when it is not true (or
the amenity went to `amenities_preferred`). Never reads user data; costs one
leaf turn (2 model calls, 1 geocode, 1 search) per input and run.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from a2a import types as a2a_types
from google.adk.a2a.converters.part_converter import convert_a2a_part_to_genai_part
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

FIXTURE = Path(__file__).resolve().parents[1] / "evals" / "amenities_must_have_inputs.jsonl"


async def _search_call(root_agent, message: str) -> dict | None:
    runner = InMemoryRunner(root_agent)
    session = await runner.session_service.create_session(app_name=runner.app_name, user_id="m")
    datapart = a2a_types.Part(root=a2a_types.DataPart(data={"query_params": {}, "profile_in": {}}))
    content = genai_types.Content(
        role="user", parts=[genai_types.Part(text=message), convert_a2a_part_to_genai_part(datapart)]
    )
    call = None
    async for event in runner.run_async(user_id="m", session_id=session.id, new_message=content):
        for part in (event.content.parts if event.content else None) or []:
            if part.function_call and part.function_call.name == "search_offers":
                call = dict(part.function_call.args or {})
    return call


def _verdict(expect: str, call: dict | None) -> bool:
    if call is None:
        return False
    must = call.get("amenities_must_have") is True
    if expect == "goal":
        return bool(call.get("amenities")) and must
    return not (must and call.get("amenities"))


async def main(runs: int) -> None:
    from hotel_search_agent.agent import root_agent

    items = [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]
    passed = {"goal": [0, 0], "plus": [0, 0]}
    for item in items:
        for _ in range(runs):
            call = await _search_call(root_agent, item["message"])
            ok = _verdict(item["expect"], call)
            passed[item["expect"]][0] += int(ok)
            passed[item["expect"]][1] += 1
            print(json.dumps({
                "id": item["id"], "expect": item["expect"], "ok": ok,
                "amenities": (call or {}).get("amenities"),
                "preferred": (call or {}).get("amenities_preferred"),
                "must_have": (call or {}).get("amenities_must_have"),
            }, ensure_ascii=False), flush=True)
    for expect, (ok, total) in passed.items():
        print(f"{expect}: {ok}/{total}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    asyncio.run(main(parser.parse_args().runs))
