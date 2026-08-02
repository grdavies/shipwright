"""Nightly notify broker path — resolve + store-write attempt (PRD 088 phase 9)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from credentials import failure_codes as fc
from credentials.environment_backend import EnvironmentBackendAdapter, register_environment_backend
from credentials.model import ResolutionState
from credentials.resolver import clear_backend_adapters
from credentials.selector_store import load_selector_store

_TEST_TOKEN = "sk_test_fixture_nightly_notify_broker_0123456789abcdef"


@pytest.fixture(autouse=True)
def _reset_backend_adapters() -> None:
    clear_backend_adapters()
    register_environment_backend()
    yield
    clear_backend_adapters()


def _planning_work_entry(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "backend": "environment",
        "provider": "github",
        "hostname": "github.com",
        "account": "grdavies",
        "allowedRepos": ["grdavies/shipwright", "grdavies/planning"],
        "allowedProjectIds": ["shipwright"],
        "allowedEndpoints": ["https://api.github.com"],
        "tokenEnv": "SW_PLANNING_ISSUES_TOKEN",
    }
    payload.update(overrides)
    return payload


def _write_selector(path: Path, entries: dict[str, dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")
    os.chmod(path, 0o600)


def _write_workflow_config(root: Path) -> None:
    cfg_dir = root / ".cursor"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "workflow.config.json").write_text(
        json.dumps(
            {
                "projectId": "shipwright",
                "host": {"provider": "github", "remote": "origin", "credentialRef": "github-work"},
                "planning": {
                    "store": {
                        "backend": "issue-store",
                        "issuesProvider": "github-issues",
                        "projectKey": "planning",
                        "storeLocation": {
                            "mode": "separate-project",
                            "owner": "grdavies",
                            "repo": "planning",
                        },
                        "issues": {"credentialRef": "planning-work"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _load_notify(repo_root: Path):
    import importlib.util
    import sys

    path = repo_root / "scripts" / "nightly-failure-notify.py"
    spec = importlib.util.spec_from_file_location("nightly_failure_notify_broker", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nightly_failure_notify_broker"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_selector_pins_planning_work_allowlists(repo_root: Path) -> None:
    """Committed CI selector keep planning-work scopes pinned."""
    selector = repo_root / ".sw" / "credential-ci-selector.json"
    data = json.loads(selector.read_text(encoding="utf-8"))
    entry = data["entries"]["planning-work"]
    assert entry["tokenEnv"] == "SW_PLANNING_ISSUES_TOKEN"
    assert "grdavies/planning" in entry["allowedRepos"]
    assert "grdavies/shipwright" in entry["allowedRepos"]
    assert "https://api.github.com" in entry["allowedEndpoints"]
    assert "shipwright" in entry["allowedProjectIds"]


def test_generated_ci_yml_scopes_token_to_notify_only(repo_root: Path) -> None:
    text = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "SW_PLANNING_ISSUES_TOKEN: ${{ secrets.SW_PLANNING_ISSUES_TOKEN }}" in text
    # Token must appear under the notify step, not the pytest verify step.
    notify_idx = text.index("Notify triage owner on nightly failure")
    token_idx = text.index("SW_PLANNING_ISSUES_TOKEN: ${{ secrets.SW_PLANNING_ISSUES_TOKEN }}")
    pytest_idx = text.index("Named plan scheduled-full-plus-integration")
    assert pytest_idx < notify_idx < token_idx
    # Pytest step block must not carry the planning token env.
    pytest_block = text[pytest_idx:notify_idx]
    assert "SW_PLANNING_ISSUES_TOKEN" not in pytest_block


def test_environment_backend_resolves_and_notify_attempts_store_write(
    tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_workflow_config(tmp_path)
    nfn = _load_notify(repo_root)

    store_calls: list[dict[str, Any]] = []

    def _fake_capture(root: Path, **kwargs: Any) -> dict[str, Any]:
        store_calls.append({"root": str(root), **kwargs})
        return {
            "unitId": "gap-999-nightly-fixture",
            "signalId": kwargs.get("signal_id"),
            "deduped": False,
            "action": "gap-capture",
        }

    monkeypatch.setattr(nfn.pgc, "capture_gap", _fake_capture)

    from credentials.model import CredentialRef, ResolvedToken, Resolution, Secret

    resolution = Resolution.resolved(
        CredentialRef("planning-work"),
        ResolvedToken(Secret(_TEST_TOKEN)),
    )

    with mock.patch("planning_store.resolve_issues_credential", return_value=resolution):
        result = nfn.notify_nightly_failure(
            tmp_path,
            {
                "job": "verify-scheduled-full-plus-integration",
                "workflowRunId": "1",
                "repository": "grdavies/shipwright",
            },
            dry_run=False,
            dedupe=False,
            require_broker=True,
        )

    assert result["verdict"] == "pass"
    assert result["credential"]["state"] == "resolved"
    assert result["credential"]["ref"] == "planning-work"
    assert store_calls, "store-write attempt (capture_gap) must run after resolve"
    assert store_calls[0].get("dry_run") is False


def test_out_of_scope_repo_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from credentials.model import CredentialRef
    from credentials.resolver import RepositoryContext, resolve_lookup

    selector = tmp_path / "selector.json"
    pairing = tmp_path / "pairings.json"
    _write_selector(
        selector,
        {
            "planning-work": _planning_work_entry(
                allowedRepos=["grdavies/shipwright"],  # planning repo excluded
            )
        },
    )
    pairing.write_text(
        json.dumps(
            {
                "version": 1,
                "pairings": [
                    {
                        "ref": "planning-work",
                        "projectId": "shipwright",
                        "remote": "https://github.com/grdavies/planning.git",
                        "approved": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SW_PLANNING_ISSUES_TOKEN", _TEST_TOKEN)

    result = resolve_lookup(
        CredentialRef("planning-work"),
        provider="github",
        purpose="planning",
        context=RepositoryContext(
            remote="https://github.com/grdavies/planning.git",
            repo_slug="grdavies/planning",
            project_id="shipwright",
            destination_endpoint="https://api.github.com",
        ),
        selector_path=selector,
        pairing_path=pairing,
        skip_integrity=True,
    )
    assert result.failure_code == fc.OUT_OF_SCOPE_REPO
    assert result.resolution.state is ResolutionState.UNRESOLVED


def test_failure_envelope_redacts_raw_exceptions(repo_root: Path) -> None:
    nfn = _load_notify(repo_root)
    assert nfn.redact_notify_error("boom secret=abc") == "notify-internal-error"
    assert nfn.redact_notify_error(fc.INSUFFICIENT_ACCESS) == fc.INSUFFICIENT_ACCESS
    assert "secret" not in nfn.redact_notify_error("token=super-secret-value")
