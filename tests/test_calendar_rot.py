"""Wave 3 of the calendar rot stops here.

Twice now a test pinned to a date literal has gone red on its own, with no code
change: PR #71 (`2026-08-05`, rolled forward by the year-roll guard) and PR #114
(`2026-09-09`, floored back to today by the carry-over guard). Both times the
guard was right and the test was wrong, and both times the red was found by the
calendar rather than by a gate.

This replays the WHOLE suite with the clock shifted forward, which is the only
check that distinguishes the two idioms the repo legitimately mixes:

  * a helper that TAKES `today` (`resolve_date_label(label, today)`) is tested
    with an explicit `_TODAY = date(...)` literal — immune, and must stay so;
  * a function deriving today INTERNALLY (`resolve_search_date`, via
    `reference_today`) must be tested clock-relatively — `date.today() +
    timedelta(...)`. A literal there is the rot.

Grepping cannot tell the two apart: the suite holds ~330 date literals across
41 files and nearly all are inert fixtures (MCP payloads, trace dumps) never
confronted with today. Shifting the clock does tell them apart, mechanically.

Runs the full suite in a subprocess (~10 s for ~3,000 tests on 2026-10-19)
rather than mutating this one's
clock, which would poison every already-imported module. The child skips this
test via `_CHILD_ENV`, so there is no recursion.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

_CHILD_ENV = "CALENDAR_ROT_CHILD"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SHIFT_DAYS = "400"  # crosses a year boundary AND moves the weekday (400 % 7 == 1)


@pytest.mark.skipif(
    os.environ.get(_CHILD_ENV) == "1",
    reason="child of the calendar-rot replay — running it again would recurse",
)
def test_no_test_in_the_suite_rots_when_the_calendar_moves_forward() -> None:
    env = {
        **os.environ,
        _CHILD_ENV: "1",
        "TIMESHIFT_DAYS": _SHIFT_DAYS,
        # `-p` resolves plugins off sys.path, and `tests/` is not a package.
        "PYTHONPATH": os.pathsep.join(
            [str(_REPO_ROOT / "tests"), os.environ.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep),
    }
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "timeshift_plugin", "--no-header"],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"The suite goes red once the calendar moves {_SHIFT_DAYS} days forward, so at least one "
        "test is pinned to a date literal that has silently stopped testing what it claims.\n"
        "Fix the TEST, not the guard: make its dates relative to the clock "
        "(`date.today() + timedelta(...)`) when the function under test derives today itself, or "
        "pass an explicit `today` when its signature accepts one.\n\n"
        f"{proc.stdout[-4000:]}\n{proc.stderr[-2000:]}"
    )
