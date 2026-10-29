"""The built widget assets (scripts/build_widget_assets.py) against their sources.

The page loads `static/dist/chat.{js,css}`, built from `static/{js,css}/chat`,
which stay the truth (the widget JS tests import them). The build is committed,
so a source edited without a rebuild would ship the OLD behaviour while every
test of the sources passes: the digest of the sources recorded in each bundle
is the guard. Offline; no node needed, except the optional byte-for-byte
rebuild below, which runs only when the pinned esbuild is on PATH.
"""
from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "build_widget_assets.py"
_spec = importlib.util.spec_from_file_location("build_widget_assets", _SCRIPT)
assert _spec is not None and _spec.loader is not None
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)

_STATIC = build.STATIC
_TEMPLATE = (_STATIC.parent / "templates" / "chat_clean.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("bundle", ["chat.js", "chat.css"])
def test_bundles_are_built_from_the_current_sources(bundle: str):
    assert build.bundle_digest(build.DIST / bundle) == build.sources_digest(), (
        f"web/vendor/static/dist/{bundle} is stale: run `python3 scripts/build_widget_assets.py`"
    )


def test_the_digest_moves_with_any_source(tmp_path: Path):
    shutil.copytree(_STATIC / "js", tmp_path / "js")
    shutil.copytree(_STATIC / "css", tmp_path / "css")
    before = build.sources_digest(tmp_path)
    (tmp_path / "css" / "chat" / "hero.css").write_text("/* edit */", encoding="utf-8")
    assert build.sources_digest(tmp_path) != before


@pytest.mark.skipif(
    not shutil.which("esbuild")
    or subprocess.run(["esbuild", "--version"], capture_output=True, text=True).stdout.strip()
    != build.ESBUILD_VERSION,
    reason=f"esbuild {build.ESBUILD_VERSION} not on PATH",
)
def test_a_rebuild_gives_the_committed_bytes(tmp_path: Path):
    build.build_bundles(tmp_path)
    for name in ("chat.js", "chat.css"):
        assert (tmp_path / name).read_bytes() == (build.DIST / name).read_bytes(), name


def test_the_page_loads_the_bundles_not_the_module_graph():
    assert '<script type="module" src="/static/dist/chat.js"></script>' in _TEMPLATE
    assert '<link rel="stylesheet" href="/static/dist/chat.css">' in _TEMPLATE
    assert "/static/js/chat/" not in _TEMPLATE
    assert "/static/css/chat/" not in _TEMPLATE


def test_every_static_file_the_page_names_exists():
    refs = set(re.findall(r"/static/([\w./-]+\.\w+)", _TEMPLATE))
    assert refs
    missing = sorted(ref for ref in refs if not (_STATIC / ref).is_file())
    assert missing == []
