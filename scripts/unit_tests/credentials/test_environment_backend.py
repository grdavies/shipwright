"""Env backend explicitness tests (PRD 080 10.3 / R6)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from credentials import failure_codes as fc
from credentials.environment_backend import (
    ENVIRONMENT_ENFORCEABILITY,
    EnvironmentBackendAdapter,
    enforceability_statement,
    read_declared_env_secret,
    register_environment_backend,
)
from credentials.model import ResolutionState
from credentials.resolver import RepositoryContext, clear_backend_adapters
from credentials.selector_store import SelectorEntry

_TEST_VALUE = "sk_test_fixture_allowlisted_secret_scan_0123456789"


def _entry(**overrides: object) -> SelectorEntry:
    payload: dict[str, object] = {
        "ref": "github-work",
        "backend": "environment",
        "provider": "github",
        "hostname": "github.com",
        "account": "work",
        "allowed_repos": ("owner/repo",),
        "allowed_project_ids": ("proj-1",),
        "allowed_endpoints": ("https://api.github.com",),
    }
    payload.update(overrides)
    return SelectorEntry(**payload)  # type: ignore[arg-type]


def _context() -> RepositoryContext:
    return RepositoryContext(
        remote="https://github.com/owner/repo.git",
        repo_slug="owner/repo",
        project_id="proj-1",
        destination_endpoint="https://api.github.com/user",
    )


def _write_selector(path: Path, entries: dict[str, dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    document = {"version": 1, "entries": entries}
    path.write_text(json.dumps(document), encoding="utf-8")
    os.chmod(path, 0o600)


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


@pytest.fixture(autouse=True)
def _reset_backend_adapters() -> None:
    clear_backend_adapters()
    register_environment_backend()
    yield
    clear_backend_adapters()


class TestEnforceabilityStatement:
    def test_publishes_explicit_only_posture(self) -> None:
        statement = enforceability_statement()
        assert statement is ENVIRONMENT_ENFORCEABILITY
        assert statement.requires_explicit_declaration is True
        assert statement.prohibits_implicit_workstation_default is True
        assert statement.presence_env_from_host_token_env is True


class TestEnvironmentBackendExplicitness:
    def test_undeclared_backend_refuses_without_reading_ambient_token(
        self,
        tmp_path: Path,
    ) -> None:
        adapter = EnvironmentBackendAdapter(
            repository_root=tmp_path,
            environ={"GITHUB_TOKEN": _TEST_VALUE},
        )
        result = adapter.resolve(_entry(), purpose="api", context=_context())
        assert result.state is ResolutionState.UNRESOLVED
        assert result.failure_code == fc.MISSING_CI_DECLARATION
        assert read_declared_env_secret(
            _entry(),
            root=tmp_path,
            environ={"GITHUB_TOKEN": _TEST_VALUE},
        ) is None

    def test_one_declared_selector_reads_host_token_env(
        self,
        tmp_path: Path,
    ) -> None:
        selector = tmp_path / "credential-selector.json"
        _write_selector(selector, {"github-work": _environment_entry()})
        adapter = EnvironmentBackendAdapter(
            repository_root=tmp_path,
            selector_path=selector,
            environ={"GITHUB_TOKEN": _TEST_VALUE},
        )
        result = adapter.resolve(_entry(), purpose="api", context=_context())
        assert result.state is ResolutionState.RESOLVED
        assert result.token is not None
        assert result.token.value == _TEST_VALUE

    def test_ambient_variable_without_declaration_is_never_used_implicitly(
        self,
        tmp_path: Path,
    ) -> None:
        undeclared = EnvironmentBackendAdapter(
            repository_root=tmp_path,
            environ={"GITHUB_TOKEN": _TEST_VALUE, "GH_TOKEN": "other-token"},
        )
        result = undeclared.resolve(_entry(), purpose="api", context=_context())
        assert result.state is ResolutionState.UNRESOLVED
        assert result.failure_code == fc.MISSING_CI_DECLARATION

        selector = tmp_path / "credential-selector.json"
        _write_selector(selector, {"github-work": _environment_entry()})
        declared = EnvironmentBackendAdapter(
            repository_root=tmp_path,
            selector_path=selector,
            environ={"GITHUB_TOKEN": _TEST_VALUE, "GH_TOKEN": "other-token"},
        )
        resolved = declared.resolve(_entry(), purpose="api", context=_context())
        assert resolved.state is ResolutionState.RESOLVED
        assert resolved.token is not None
        assert resolved.token.value == _TEST_VALUE

    def test_empty_token_after_declaration_fails_closed(
        self,
        tmp_path: Path,
    ) -> None:
        selector = tmp_path / "credential-selector.json"
        _write_selector(selector, {"github-work": _environment_entry()})
        adapter = EnvironmentBackendAdapter(
            repository_root=tmp_path,
            selector_path=selector,
            environ={},
        )
        result = adapter.resolve(_entry(), purpose="api", context=_context())
        assert result.state is ResolutionState.UNRESOLVED
        assert result.failure_code == fc.INSUFFICIENT_ACCESS
