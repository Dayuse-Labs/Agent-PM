"""Read-only, bounded production export. Raw data belongs under ignored baseline/.

The legacy API uses descending offset pagination, with no server-side cutoff.
Pin the initial ID ceiling, overlap pages, deduplicate, and require the original
row count before declaring a complete snapshot. Events can exceed the API's
100000 offset ceiling; partition those by their observed event names and verify
the union against the initial total. A missing partition is an error, not success.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

Fetch = Callable[[str, dict[str, Any]], dict[str, Any]]


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def snapshot(fetch: Fetch, endpoint: str, directory: Path, page_size: int = 1000) -> dict:
    if not 2 <= page_size <= 10000:
        raise ValueError("page_size must be between 2 and 10000")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_path = directory / "snapshot.json"
    rows_path = directory / "rows.jsonl"
    rows: dict[int, dict] = {}
    if rows_path.exists():
        rows = {int(x["id"]): x for x in map(json.loads, rows_path.read_text().splitlines())}
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if state["endpoint"] != endpoint:
            raise ValueError("snapshot endpoint changed")
        if state.get("complete"):
            if len(rows) != state["initial_total"]:
                raise ValueError("completed snapshot row count changed")
            if hashlib.sha256(rows_path.read_bytes()).hexdigest() != state["sha256"]:
                raise ValueError("completed snapshot content changed")
            return state
    else:
        first = fetch(endpoint, {"limit": page_size, "offset": 0})
        initial = first["records"]
        state = {
            "endpoint": endpoint, "started_at": datetime.now(UTC).isoformat(),
            "initial_total": int(first["total"]),
            "max_id": max((int(x["id"]) for x in initial), default=0),
            "complete": False,
        }
        atomic_json(state_path, state)
        rows.update((int(x["id"]), x) for x in initial)

    def persist() -> None:
        tmp = rows_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            for row in sorted(rows.values(), key=lambda x: (x["created_at"], int(x["id"]))):
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        tmp.chmod(0o600)
        tmp.replace(rows_path)
        state["captured_rows"] = len(rows)
        atomic_json(state_path, state)

    def sweep(filters: dict[str, str]) -> None:
        offset = 0
        overlap = min(50, max(1, page_size // 10))
        previous_ids: set[int] | None = None
        while offset <= 100000:
            page = fetch(endpoint, {"limit": page_size, "offset": offset, **filters})
            items = page["records"]
            page_ids = {int(x["id"]) for x in items}
            if page_ids and page_ids == previous_ids:
                break  # offset was clamped, or the server returned the same page
            previous_ids = page_ids
            rows.update((int(x["id"]), x) for x in items if int(x["id"]) <= state["max_id"])
            persist()
            print(json.dumps({"source": endpoint, "rows": len(rows), "expected": state["initial_total"],
                              "offset": offset, "partition": filters}), flush=True)
            if not items or len(items) < page_size:
                break
            offset += page_size - overlap

    sweep({})
    if len(rows) != state["initial_total"] and endpoint.endswith("/events"):
        for event in sorted({str(x["event"]) for x in rows.values() if x.get("event")}):
            sweep({"event": event})
            if len(rows) == state["initial_total"]:
                break
    # Retry an offset sweep once: concurrent insertions may have moved a boundary.
    if len(rows) != state["initial_total"]:
        sweep({})
    state["complete"] = len(rows) == state["initial_total"]
    state["finished_at"] = datetime.now(UTC).isoformat()
    persist()
    state["sha256"] = hashlib.sha256(rows_path.read_bytes()).hexdigest()
    atomic_json(state_path, state)
    if not state["complete"]:
        raise RuntimeError(f"Incomplete snapshot: {len(rows)}/{state['initial_total']} unique bounded rows")
    return state


def http_fetch(base: str, api_key: str) -> Fetch:
    def fetch(path: str, params: dict[str, Any]) -> dict:
        url = base.rstrip("/") + path + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"X-Internal-Api-Key": api_key})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    body = json.load(response)
                if body.get("status") != "ok" or not isinstance(body.get("records"), list):
                    raise ValueError("unexpected export response schema")
                return body
            except (OSError, ValueError):
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        raise AssertionError("unreachable")
    return fetch


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://ai.dayuse.com")
    parser.add_argument("--source", choices=["logs", "events"], required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--page-size", type=int, default=1000)
    args = parser.parse_args()
    key = os.environ.get("CHAT_API_KEY")
    if not key:
        parser.error("CHAT_API_KEY must be set in the environment")
    result = snapshot(http_fetch(args.base_url, key), "/v3/chat/" + args.source,
                      args.output, args.page_size)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
