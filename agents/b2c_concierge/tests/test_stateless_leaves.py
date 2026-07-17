"""Static invariant: the leaves are stateless (decision B3) — the session
Redis belongs to the orchestrator only (profile.py / profile_store.py under
b2c_concierge). Lowercase `redis` (the package/import name — an
`import redis`, a `redis==...` requirements pin) must never appear anywhere
under the two leaf packages: nothing pulls the dependency in or reaches for
it, ever. Matches the DoD's own `grep -rn "redis"` exactly — deliberately
case-SENSITIVE: both leaves already document the invariant in prose as
"Redis" (capitalized), which must keep passing."""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LEAF_DIRS = ("hotel_search_agent", "faq_agent")
_SKIP_DIR_NAMES = {"__pycache__", ".pytest_cache", ".adk", ".git"}


def _redis_mentions() -> list[str]:
    hits: list[str] = []
    for leaf in _LEAF_DIRS:
        leaf_dir = _REPO_ROOT / "agents" / leaf
        for path in leaf_dir.rglob("*"):
            if not path.is_file() or _SKIP_DIR_NAMES & set(path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if "redis" in line:
                    hits.append(f"{path.relative_to(_REPO_ROOT)}:{lineno}: {line.strip()}")
    return hits


def test_no_redis_reference_in_leaf_agents():
    """A `redis` mention in a leaf would mean it started keeping its own
    state — a contract violation of the stateless-leaves decision (B3)."""
    hits = _redis_mentions()
    assert not hits, "leaf(s) reference redis — leaves must stay stateless:\n" + "\n".join(hits)
