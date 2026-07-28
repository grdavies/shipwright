"""CI declaration path tests (PRD 080 10.4 / R6)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from credentials import failure_codes as fc
from credentials.ci_declaration import (
    MISSING_CI_DECLARATION_REMEDIATION,
    ci_selector_path,
    deprecation_release_preflight,
    detect_ambient_token_without_declaration,
    is_environment_backend_declared,
    is_github_actions,
    load_ci_selector_store,
)
from credentials.environment_backend import EnvironmentBackendAdapter
from credentials.model import ResolutionState
from credentials.resolver import RepositoryContext
from credentials.selector_store import SelectorStoreError

_TEST_VALUE = "sk_test_fixture_allowlisted_secret_scan_0123456789"


def _context() -> RepositoryContext:
    return RepositoryContext(
        remote="https://github.com/owner/repo.git",
        repo_slug="owner/repo",
        project_id="proj-1",
        destination_endpoint="https://api.github.com/user",
    )


def _write_ci_selector(root: Path, entries: dict[str, dict[str, object]]) -> Path:
    path = ci_selector_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {"version": 1, "entries": entries}
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _environment_entry(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "backend": "environment",
        "provider": "github",
        "hostname": "github.com",
        "account": "work",
        "allowedRepos": ["owner/repo"],
        "allowedProjectIds": ["proj-1"],
        "allowedEndpoints": ["https://api.github.com"],
    }
    payload.update(overrides)
    return payload


class TestGithubActionsMarker:
    def test_detects_actions_marker(self) -> None:
        assert is_github_actions({"GITHUB_ACTIONS": "true"})
        assert not is_github_actions({})


class TestCiSelectorResolution:
    def test_repository_declared_env_selector_resolves_without_machine_local_file(
        self,
        tmp_path: Path,
    ) -> None:
        _write_ci_selector(tmp_path, {"github-work": _environment_entry()})
        document = load_ci_selector_store(root=tmp_path)
        assert "github-work" in document.entries
        assert document.entries["github-work"].backend == "environment"
        assert is_environment_backend_declared("github-work", root=tmp_path)

        entry = document.entries["github-work"]
        adapter = EnvironmentBackendAdapter(
            repository_root=tmp_path,
            environ={"GITHUB_ACTIONS": "true", "GITHUB_TOKEN": _TEST_VALUE},
        )
        result = adapter.resolve(entry, purpose="api", context=_context())
        assert result.state is ResolutionState.RESOLVED
        assert result.token is not None
        assert result.token.value == _TEST_VALUE

    def test_missing_ci_selector_fails_closed(self, tmp_path: Path) -> None:
        with pytest.raises(SelectorStoreError, match="ci-selector-absent"):
            load_ci_selector_store(root=tmp_path)


class TestDeprecationReleasePreflight:
    def test_preflight_fails_with_durable_remediation_when_neither_declaration_exists(
        self,
        tmp_path: Path,
    ) -> None:
        result = deprecation_release_preflight(
            root=tmp_path,
            token_env="GITHUB_TOKEN",
            environ={},
        )
        assert result.verdict == "fail"
        assert result.code == fc.MISSING_CI_DECLARATION
        assert result.remediation == fc.failure_detail(fc.MISSING_CI_DECLARATION).hint
        assert not result.local_declared
        assert not result.ci_declared

    def test_preflight_detects_ambient_token_without_declaration_in_actions(
        self,
        tmp_path: Path,
    ) -> None:
        ambient = detect_ambient_token_without_declaration(
            root=tmp_path,
            token_env="GITHUB_TOKEN",
            environ={"GITHUB_ACTIONS": "true", "GITHUB_TOKEN": _TEST_VALUE},
        )
        assert ambient.detected is True
        assert ambient.remediation == MISSING_CI_DECLARATION_REMEDIATION

        result = deprecation_release_preflight(
            root=tmp_path,
            token_env="GITHUB_TOKEN",
            environ={"GITHUB_ACTIONS": "true", "GITHUB_TOKEN": _TEST_VALUE},
        )
        assert result.verdict == "fail"
        assert result.code == fc.MISSING_CI_DECLARATION
        assert result.remediation == MISSING_CI_DECLARATION_REMEDIATION
        assert result.ambient_finding is not None
        assert result.ambient_finding.detected is True

    def test_preflight_passes_when_ci_declaration_exists(
        self,
        tmp_path: Path,
    ) -> None:
        _write_ci_selector(tmp_path, {"github-work": _environment_entry()})
        result = deprecation_release_preflight(
            root=tmp_path,
            token_env="GITHUB_TOKEN",
            environ={"GITHUB_ACTIONS": "true", "GITHUB_TOKEN": _TEST_VALUE},
        )
        assert result.verdict == "pass"
        assert result.ci_declared is True
        assert result.code is None
