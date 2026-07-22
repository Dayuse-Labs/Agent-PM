"""Build the eval-pack manifest and optional deterministic share archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path

PACK = Path(__file__).resolve().parent
ROOT = PACK.parent


def _sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes())
    return digest.hexdigest()


def _git_value(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def build_manifest() -> dict:
    suites = {}
    total = 0
    for path in sorted((PACK / "cases").glob("*.jsonl")):
        count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        suites[path.stem] = {"file": f"cases/{path.name}", "cases": count, "sha256": _sha256(path)}
        total += count
    fixture_manifest_path = PACK / "fixtures/inventory_snapshot_manifest.json"
    fixture_manifest = (
        json.loads(fixture_manifest_path.read_text(encoding="utf-8"))
        if fixture_manifest_path.exists()
        else None
    )
    return {
        "schema_version": "1.0",
        "pack_version": "2026.07.21-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "repository_commit": _git_value("rev-parse", "HEAD"),
        "repository_branch": _git_value("branch", "--show-current"),
        "deployed_commit": None,
        "deployed_commit_verified": False,
        "warning": (
            "A production baseline and deployed commit could not be generated without approved "
            "production credentials. Run the pack against the verified deployed endpoint before comparison."
        ),
        "privacy": {
            "raw_session_ids_included": False,
            "customer_pii_included": False,
            "prod_references": "salted one-way short hashes only",
        },
        "total_cases": total,
        "suites": suites,
        "inventory_fixture": fixture_manifest,
        "baseline": {
            "included": False,
            "instructions": "See baselines/README.md",
        },
    }


def write_manifest() -> Path:
    path = PACK / "manifest.json"
    path.write_text(json.dumps(build_manifest(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def create_archive(output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    members: list[Path] = []
    for path in PACK.rglob("*"):
        if not path.is_file():
            continue
        if (
            path == output
            or "__pycache__" in path.parts
            or "results" in path.parts
            or "dist" in path.parts
        ):
            continue
        members.append(path)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        readme = PACK / "README.md"
        root_info = zipfile.ZipInfo("dayuse_eval_pack/README.md")
        root_info.date_time = (2026, 7, 21, 0, 0, 0)
        root_info.compress_type = zipfile.ZIP_DEFLATED
        root_info.external_attr = 0o644 << 16
        archive.writestr(root_info, readme.read_bytes())
        for path in sorted(members):
            info = zipfile.ZipInfo(f"dayuse_eval_pack/eval_pack/{path.relative_to(PACK)}")
            info.date_time = (2026, 7, 21, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
        tests = ROOT / "tests/unit/eval_pack/test_runner.py"
        if tests.exists():
            test_info = zipfile.ZipInfo("dayuse_eval_pack/tests/test_runner.py")
            test_info.date_time = (2026, 7, 21, 0, 0, 0)
            test_info.compress_type = zipfile.ZIP_DEFLATED
            test_info.external_attr = 0o644 << 16
            archive.writestr(test_info, tests.read_bytes())
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = write_manifest()
    print(f"Manifest: {manifest}")
    if args.archive:
        archive = create_archive(Path(args.archive))
        print(f"Archive: {archive}")
        print(f"Archive SHA256: {_sha256(archive)}")


if __name__ == "__main__":
    main()
