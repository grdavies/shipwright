"""Provider adapter round-trip fixtures (PRD 082 phase 13 / R27)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_store as ps
from _planning_pkg_loader import load_backends_package, load_providers_package, load_submodule

_boundary = load_submodule("providers._boundary")
provider_import_violations = _boundary.provider_import_violations

backends = load_backends_package()
providers = load_providers_package()

SAMPLE_CONTENT = "---\nunitId: parity-unit\ntitle: Parity\n---\n\n# Parity body\n"
UNIT_ID = "parity-unit"
BODY_PATH = "docs/planning/parity-unit/body.md"


def _issue_store_cfg(provider: str) -> dict:
    issues: dict = {"provider": provider, "tokenEnv": f"ISSUES_{provider.upper().replace('-', '_')}_TOKEN"}
    if provider == "jira":
        issues.update(
            {
                "endpoint": "https://fixture.atlassian.net",
                "flavor": "dc",
                "issueType": "Task",
            }
        )
    if provider == "linear":
        issues["teamKey"] = "ENG"
    return {
        "version": 1,
        "planning": {
            "store": {
                "backend": "issue-store",
                "projectKey": "demo",
                "storeLocation": {"mode": "separate-project", "owner": "acme", "repo": "planning"},
                "issues": issues,
            }
        },
    }


def _write_config(root: Path, cfg: dict) -> None:
    cfg_dir = root / ".cursor"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    host = {
        "provider": "github",
        "remote": "origin",
        "ssrfAllowlist": ["api.github.com", "gitlab.com", "api.linear.app", "fixture.atlassian.net"],
    }
    payload = {"projectId": "acme-demo", "host": host, **cfg}
    (cfg_dir / "workflow.config.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize(
    "provider",
    ["github-issues", "gitlab-issues", "jira", "linear"],
)
def test_provider_fixture_round_trips_through_issue_adapter(
    tmp_path: Path,
    provider: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    cfg = _issue_store_cfg(provider)
    _write_config(tmp_path, cfg)
    backend = backends.IssueStoreBackend(tmp_path, cfg)
    put = backend.put(UNIT_ID, BODY_PATH, SAMPLE_CONTENT)
    assert put.verdict == "ok"
    got = backend.get(UNIT_ID, BODY_PATH)
    assert got.verdict == "ok"
    assert got.content is not None
    assert UNIT_ID in got.content
    assert "# Parity body" in got.content
    exists = backend.exists(UNIT_ID, BODY_PATH)
    assert exists.verdict == "ok"


def test_provider_adapters_expose_scope_probes() -> None:
    for provider_id, module in providers.PROVIDER_MODULES.items():
        if provider_id != "linear":
            assert hasattr(module, "scope_probe")
        assert hasattr(module, "destination_endpoint")
        assert hasattr(module, "wire_client")


def test_provider_import_outside_package_rejected() -> None:
    violations = provider_import_violations(REPO_ROOT)
    assert violations == [], "\n".join(violations)


def test_planning_store_delegates_github_scope_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _issue_store_cfg("github-issues")
    _write_config(tmp_path, cfg)

    def boom(*_a, **_k):
        raise AssertionError("scope_probe should delegate")

    monkeypatch.setattr(providers.github, "scope_probe", boom)
    with pytest.raises(AssertionError):
        ps._github_scope_probe("token", cfg, tmp_path)


def test_issues_destination_endpoint_delegates_to_providers() -> None:
    cfg = _issue_store_cfg("github-issues")
    assert ps._issues_destination_endpoint(cfg, "github-issues") == providers.github.destination_endpoint(cfg)
