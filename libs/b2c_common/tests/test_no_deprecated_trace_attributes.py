"""CI lock (OBS4): the trace-level Langfuse attributes deprecated in v4 must
never come back into our code.

`langfuse.trace.input` / `.output` / `.name` were this codebase's ONLY
deprecated surface (brief §12.4): in v4 a trace's input/output/name come from
its ROOT observation, not from attributes stamped on an arbitrary span. OBS1
used them in `stamp_langfuse_session` because ADK's root span carries no
attributes; OBS4 removed the need by opening a real root observation on both
the concierge (`turn_observation`) and the A2A surfaces (`A2aTurnObservation`).

The grep is the proof this stays solved, so it lives in the suite instead of a
one-off terminal check.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Our whole application code — the two zones OBS4 owns. `.venv` and the docs
#: are deliberately out: the contract document NAMES these attributes to
#: explain what was removed, which is the opposite of a regression.
SOURCE_DIRS = ("agents", "libs")

DEPRECATED_TRACE_ATTRIBUTES = (
    "langfuse.trace.input",
    "langfuse.trace.output",
    "langfuse.trace.name",
)


def _source_files() -> list[Path]:
    files: list[Path] = []
    for directory in SOURCE_DIRS:
        files += [
            path
            for path in (REPO_ROOT / directory).rglob("*.py")
            if "__pycache__" not in path.parts and path != Path(__file__)
        ]
    return files


def test_there_are_source_files_to_scan():
    # The lock must be scanning something real (the 3 agents + the shared lib).
    assert len(_source_files()) > 30


def test_no_deprecated_trace_level_attributes_anywhere():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {attribute}"
        for path in _source_files()
        for attribute in DEPRECATED_TRACE_ATTRIBUTES
        if attribute in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert offenders == [], (
        f"deprecated Langfuse trace-level attribute(s) found: {offenders} — in v4 a trace's "
        "input/output/name come from its ROOT observation (see "
        "OBS4-TRACE-PROPAGATION-CONTRACT.md §4). Set them on the root observation instead."
    )
