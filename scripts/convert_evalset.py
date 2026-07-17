#!/usr/bin/env python
"""Convert evalset/evalset-v0.json (32 anonymized prod scenarios, 8 families) to the
ADK evalset format → evalset/evalset-v0.adk.json (S3 step 5).

Mapping:
- one scenario → one EvalCase (eval_id keeps the family-prefixed id);
- each user turn → one Invocation (multi-turn conversations preserved);
- the scenario's `expected` rubric → final_response reference of the LAST turn.
  It is a RUBRIC, not a verbatim answer: with response_match_score (ROUGE) the
  scores are indicative only — functional failures are TOLERATED at the S2/S3
  skeleton stage (the criteria bar lives in evalset/test_config.json). A proper
  LLM-judge rubric criteria lands with the quality sessions.

The output is validated against the installed ADK pydantic schema before writing.
Regenerate after editing evalset-v0.json:  .venv/bin/python scripts/convert_evalset.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from google.adk.evaluation.eval_case import EvalCase, Invocation
from google.adk.evaluation.eval_set import EvalSet
from google.genai import types as genai_types

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evalset" / "evalset-v0.json"
TARGET = ROOT / "evalset" / "evalset-v0.adk.json"


def convert() -> EvalSet:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    cases: list[EvalCase] = []
    for scenario in source["scenarios"]:
        turns = scenario["user_turns"]
        conversation = [
            Invocation(
                invocation_id=f"{scenario['id']}-t{i}",
                user_content=genai_types.Content(
                    role="user", parts=[genai_types.Part(text=turn)]
                ),
                final_response=(
                    genai_types.Content(
                        role="model", parts=[genai_types.Part(text=scenario["expected"])]
                    )
                    if i == len(turns) - 1
                    else None
                ),
            )
            for i, turn in enumerate(turns)
        ]
        cases.append(EvalCase(eval_id=scenario["id"], conversation=conversation))
    return EvalSet(
        eval_set_id="agentb2c-evalset-v0",
        name=f"AgentB2C v0 — {len(cases)} scénarios prod anonymisés, 8 familles",
        description=(
            "Converted from evalset-v0.json (source: conversation_logs prod 30j, anonymized). "
            "final_response holds the family RUBRIC, not a verbatim answer — scores are "
            "indicative until an LLM-judge criteria replaces response_match_score."
        ),
        eval_cases=cases,
    )


def main() -> int:
    eval_set = convert()
    TARGET.write_text(
        eval_set.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8"
    )
    families = len({case.eval_id.split("-")[0] for case in eval_set.eval_cases})
    print(f"wrote {TARGET.relative_to(ROOT)}: {len(eval_set.eval_cases)} cases, {families} families")
    return 0


if __name__ == "__main__":
    sys.exit(main())
