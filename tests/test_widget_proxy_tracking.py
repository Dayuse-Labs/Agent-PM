"""Offline tests for what the widget proxy does for Amplitude tracking
(scripts/run_widget_proxy.py): it bakes the deployed version into the page as
`agent_version`, serves the pinned Session Replay config on `/sr-config`, and
has no `/api/track` route.
The `X-Dayuse-Synthetic` forwarding is covered by test_widget_proxy_auth.py.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "run_widget_proxy.py"
_spec = importlib.util.spec_from_file_location("run_widget_proxy_tracking", _SCRIPT)
assert _spec is not None and _spec.loader is not None
wp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wp)

_VENDOR = _REPO / "web" / "vendor"


def _agent_version_meta(html: str) -> str:
    match = re.search(r'<meta name="agent-version" content="([^"]*)">', html)
    assert match, "the page carries no agent-version meta"
    return match.group(1)


class TestAgentVersionMeta:
    def test_the_deployed_release_is_baked_into_the_page(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_RELEASE", "130caed")
        html = wp.render_index(_VENDOR).decode("utf-8")
        assert _agent_version_meta(html) == "130caed"

    @pytest.mark.parametrize("release", [None, "", "   "])
    def test_no_release_reads_unknown(self, monkeypatch, release):
        if release is None:
            monkeypatch.delenv("LANGFUSE_RELEASE", raising=False)
        else:
            monkeypatch.setenv("LANGFUSE_RELEASE", release)
        html = wp.render_index(_VENDOR).decode("utf-8")
        assert _agent_version_meta(html) == "unknown"

    def test_the_release_cannot_break_out_of_the_attribute(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_RELEASE", '"><script>x</script>')
        html = wp.render_index(_VENDOR).decode("utf-8")
        assert "<script>x</script>" not in html
        assert _agent_version_meta(html) == "&quot;&gt;&lt;script&gt;x&lt;/script&gt;"


class TestTrackBeaconRetired:
    def test_api_track_is_not_found(self):
        handler = wp.WidgetProxyHandler.__new__(wp.WidgetProxyHandler)
        handler.path = "/api/track"
        errors: list[int] = []
        handler.send_error = lambda code, *a, **k: errors.append(code)
        handler.send_response = lambda *a, **k: pytest.fail("/api/track was answered")
        handler.do_POST()
        assert errors == [404]


def _get(path: str) -> tuple[dict, bytes]:
    handler = wp.WidgetProxyHandler.__new__(wp.WidgetProxyHandler)
    handler.agent_usa_dir = _VENDOR
    handler.backend = "http://127.0.0.1:8100"
    handler.path = path
    sent: dict = {"status": None, "headers": {}}
    handler.send_response = lambda code, *a: sent.__setitem__("status", code)  # noqa: ARG005
    handler.send_header = lambda k, v: sent["headers"].__setitem__(k, v)
    handler.end_headers = lambda: None
    written = bytearray()
    handler.wfile = type("Wfile", (), {"write": lambda self, b: written.extend(b)})()
    handler.do_GET()
    return sent, bytes(written)


class TestSessionReplayConfig:
    def test_serves_the_contract_sample_rate_as_uncached_json(self):
        contract = json.loads((_REPO / "contracts" / "amplitude_events.json").read_text())
        sent, body = _get("/sr-config")
        assert sent["status"] == 200
        assert sent["headers"]["Content-Type"] == "application/json"
        assert sent["headers"]["Cache-Control"] == "no-store"
        sampling = json.loads(body)["configs"]["sessionReplay"]["sr_sampling_config"]
        assert sampling == {
            "capture_enabled": True,
            "sample_rate": contract["session_replay"]["sample_rate"],
        }

    def test_leaves_privacy_masking_to_the_local_default(self):
        _, body = _get("/sr-config")
        assert "sr_privacy_config" not in json.loads(body)["configs"]["sessionReplay"]

    def test_ignores_the_query_string(self):
        _, plain = _get("/sr-config")
        sent, queried = _get("/sr-config?api_key=k&config_keys=sessionReplay&session_id=1")
        assert sent["status"] == 200
        assert queried == plain
