"""Repo-root pytest conftest — offline invariant, enforced.

`import litellm` calls `load_dotenv()` (litellm/__init__.py), so any secret in
the developer's repo-root `.env` silently lands in os.environ of EVERY test
process. With real LANGFUSE_* keys that turned the suite into a live span
exporter (and hung the serve-auth tests on repeated TestClient lifespans).

Neutralize by setting the keys to EMPTY strings before any test module import:
load_dotenv(override=False) never overwrites an existing variable, and
b2c_common.observability treats empty as disabled. Same treatment for any
future opt-in observability key — the suite must stay network-free whatever
the local .env contains.
"""
import os

for _key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
    os.environ[_key] = ""

# Same for the prod-parity knobs a local .env carries (per-role models,
# reasoning cap, leaf timeout): the suite asserts the code defaults.
for _key in (
    "DAYUSE_MODEL_TRIAGE",
    "DAYUSE_MODEL_SYNTHESIS",
    "DAYUSE_REASONING_EFFORT",
    "DAYUSE_REASONING_EFFORT_TRIAGE",
    "DAYUSE_REASONING_EFFORT_SYNTHESIS",
    "DAYUSE_REASONING_EFFORT_JUDGE",
    "RELEASE_GATE_JUDGE_MODEL",
    "CONCIERGE_LEAF_TIMEOUT_SECONDS",
):
    os.environ[_key] = ""
