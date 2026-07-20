"""b2c-concierge evaluation harness (S08): conversational battery + LLM judge.

Public surface:
- `battery.load_scenarios` / `battery.run_battery` — the conversational battery.
- `judge.LLMJudge` — the LLM-as-judge (via LiteLLM).
The release gate (`scripts/run_release_gate.py`) compares a battery run against
the committed `baselines.json` and decides merge / don't-merge.
"""
