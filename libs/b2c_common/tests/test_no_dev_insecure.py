"""CI lock (S3 step 3): `dev-insecure` is usable locally ONLY — this test fails if the
string reaches any deployment-facing config (Dockerfiles, CI workflows, container/infra
manifests). The lib's DevInsecureIdentityProvider accepts any caller; deploying it would
void D7 entirely."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Everything that shapes a deployed environment. Extend when railway/k8s manifests appear.
DEPLOY_CONFIG_GLOBS = (
    "agents/*/Dockerfile",
    "Dockerfile*",
    ".github/workflows/*",
    "**/railway*.json",
    "**/railway*.toml",
    "**/*.k8s.yaml",
    "**/k8s/**/*.yaml",
    "**/docker-compose*.yml",
    "**/docker-compose*.yaml",
)


def _deploy_config_files() -> list[Path]:
    files: list[Path] = []
    for pattern in DEPLOY_CONFIG_GLOBS:
        files += [
            p for p in REPO_ROOT.glob(pattern)
            if p.is_file() and ".venv" not in p.parts and "node_modules" not in p.parts
        ]
    return files


def test_deploy_configs_exist_to_scan():
    # The lock must be scanning something real (the 3 Dockerfiles at minimum).
    names = {p.name for p in _deploy_config_files()}
    assert "Dockerfile" in names


def test_no_dev_insecure_in_deploy_configs():
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in _deploy_config_files()
        if "dev-insecure" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert offenders == [], (
        f"'dev-insecure' found in deployment config(s): {offenders} — the dev-insecure "
        "identity provider accepts ANY caller and must never be deployed (D7)."
    )
