"""CI declaration path tests (PRD 080 10.4 / R6; PRD 084 R1)."""

from __future__ import annotations

import json
import subprocess
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
from credentials.selector_store import SelectorStoreError, load_selector_store
from init_credential_migration import (
    DetectedAccount,
    apply_guided_single_identity,
    build_init_plan,
    offer_ci_env_declaration,
)

_TEST_VALUE = "sk_test_fixture_allowlisted_secret_scan_0123456789"


def _init_git_remote(root: Path, remote: str = "https://github.com/owner/repo.git") -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=root, check=True)


def _write_config(root: Path, payload: dict[str, object]) -> None:
    path = root / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _one_account_detector(_root: Path) -> tuple[DetectedAccount, ...]:
    return (
        DetectedAccount(
            provider="github",
            hostname="github.com",
            account="work",
        ),
    )


def _github_host_entry() -> dict[str, object]:
    return {
        "backend": "environment",
        "provider": "github",
        "hostname": "github.com",
        "account": "work",
        "allowedRepos": ["owner/repo"],
        "allowedProjectIds": ["proj-1"],
        "allowedEndpoints": ["https://api.github.com"],
    }


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


class TestLoopbackProviderSuppression:
    def test_loopback_memory_provider_gets_no_github_entry(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        _write_config(
            root,
            {
                "memory": {
                    "provider": "recallium",
                    "connection": {"restBaseUrl": "http://127.0.0.1:8001"},
                }
            },
        )
        selector = tmp_path / "credential-selector.json"
        selector.write_text(
            json.dumps({"version": 1, "entries": {"memory-work": _github_host_entry()}}),
            encoding="utf-8",
        )
        plan = build_init_plan(
            root,
            selector_path=selector,
            account_detector=_one_account_detector,
        )
        result = apply_guided_single_identity(
            root,
            plan,
            confirm=True,
            selector_path=selector,
        )
        assert result["verdict"] == "ok"
        document = load_selector_store(path=selector, skip_integrity=True)
        assert "github-work" in document.entries
        assert document.entries["github-work"].provider == "github"
        assert "memory-work" not in document.entries

        ci_result = offer_ci_env_declaration(root, plan, confirm=True)
        assert ci_result["verdict"] == "ok"
        ci_document = json.loads(ci_selector_path(root).read_text(encoding="utf-8"))
        assert "github-work" in ci_document["entries"]
        assert "memory-work" not in ci_document["entries"]

    def test_git_host_single_provider_path_unchanged(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        selector = tmp_path / "credential-selector.json"
        plan = build_init_plan(
            root,
            selector_path=selector,
            account_detector=_one_account_detector,
        )
        result = apply_guided_single_identity(
            root,
            plan,
            confirm=True,
            selector_path=selector,
        )
        assert result["verdict"] == "ok"
        document = load_selector_store(path=selector, skip_integrity=True)
        assert "github-work" in document.entries
        assert "planning-work" in document.entries
        assert "memory-work" in document.entries
        assert document.entries["memory-work"].provider == "github"
        assert document.entries["memory-work"].allowed_endpoints == ("https://api.github.com",)

        ci_result = offer_ci_env_declaration(root, plan, confirm=True)
        assert ci_result["verdict"] == "ok"
        ci_document = load_ci_selector_store(root=root)
        assert "memory-work" in ci_document.entries
        assert ci_document.entries["memory-work"].provider == "github"
