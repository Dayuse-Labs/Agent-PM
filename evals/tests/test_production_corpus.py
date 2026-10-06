import json

import pytest

from evals.production_corpus import snapshot


def row(i):
    return {"id": i, "created_at": f"2026-10-06T00:00:{i:02d}Z", "event": "click"}


def test_insertions_between_offset_pages_do_not_change_snapshot(tmp_path):
    calls = 0

    def fetch(path, params):
        nonlocal calls
        calls += 1
        data = [row(i) for i in range(5 if calls == 1 else 6, 0, -1)]
        start = params["offset"]
        return {"records": data[start:start + params["limit"]], "total": len(data)}

    state = snapshot(fetch, "/v3/chat/logs", tmp_path, 3)
    assert state["complete"]
    assert state["captured_rows"] == 5
    assert [json.loads(line)["id"] for line in (tmp_path / "rows.jsonl").read_text().splitlines()] == [1, 2, 3, 4, 5]


def test_clamped_or_missing_pages_cannot_report_success(tmp_path):
    def fetch(path, params):
        return {"records": [row(4), row(3)], "total": 4}

    with pytest.raises(RuntimeError, match="Incomplete snapshot"):
        snapshot(fetch, "/v3/chat/logs", tmp_path, 2)
    assert not json.loads((tmp_path / "snapshot.json").read_text())["complete"]


def test_completed_export_is_resumable_and_content_verified(tmp_path):
    def fetch(path, params):
        data = [row(2), row(1)]
        start = params["offset"]
        return {"records": data[start:start + params["limit"]], "total": 2}

    snapshot(fetch, "/v3/chat/logs", tmp_path, 2)

    def no_network(*args):
        raise AssertionError("completed snapshot must not fetch again")

    assert snapshot(no_network, "/v3/chat/logs", tmp_path, 2)["complete"]
    content = (tmp_path / "rows.jsonl").read_text().replace('"click"', '"changed"')
    (tmp_path / "rows.jsonl").write_text(content)
    with pytest.raises(ValueError, match="content changed"):
        snapshot(no_network, "/v3/chat/logs", tmp_path, 2)


def test_events_recover_rows_using_partitions(tmp_path):
    def fetch(path, params):
        if params.get("event"):
            data = [row(4), row(3), row(2), row(1)]
            start = params["offset"]
            return {"records": data[start:start + params["limit"]], "total": 4}
        return {"records": [row(4), row(3)], "total": 4}

    assert snapshot(fetch, "/v3/chat/events", tmp_path, 2)["captured_rows"] == 4
