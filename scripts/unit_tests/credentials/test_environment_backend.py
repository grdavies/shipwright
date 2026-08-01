"""Env backend explicitness tests (PRD 080 10.3 / R6)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from credentials import failure_codes as fc
from credentials.ci_declaration import resolve_presence_env_name
from credentials.environment_backend import (
    ENVIRONMENT_ENFORCEABILITY,
    EnvironmentBackendAdapter,
    enforceability_statement,
    read_declared_env_secret,
    register_environment_backend,
)
from credentials.model import ResolutionState
from credentials.resolver import RepositoryContext, clear_backend_adapters
from credentials.selector_store import SelectorEntry, load_selector_store
from init_credential_migration import build_selector_entry

_TEST_VALUE = "sk_test_fixture_allowlisted_secret_scan_0123456789"
_ENTRY_TOKEN_VALUE = "sk_test_fixture_entry_token_env_override_0123456789"
_HOST_TOKEN_VALUE = "sk_test_fixture_host_token_env_fallback_0123456789"
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "core"
    / "sw-reference"
    / "credential-selector.schema.json"
)


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


def _write_workflow_config(root: Path, host: dict[str, object]) -> None:
    cfg_dir = root / ".cursor"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "workflow.config.json").write_text(
        json.dumps({"projectId": "proj-1", "host": host}),
        encoding="utf-8",
    )


def _validate_selector_document(document: dict[str, object]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(document, schema)


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


class TestPerEntryTokenEnv:
    def test_entry_token_env_resolves_over_host_token_env(self, tmp_path: Path) -> None:
        _write_workflow_config(tmp_path, {"provider": "github", "tokenEnv": "HOST_GITHUB_TOKEN"})
        selector = tmp_path / "credential-selector.json"
        _write_selector(
            selector,
            {"github-work": _environment_entry(tokenEnv="ENTRY_GITHUB_TOKEN")},
        )
        adapter = EnvironmentBackendAdapter(
            repository_root=tmp_path,
            selector_path=selector,
            environ={
                "ENTRY_GITHUB_TOKEN": _ENTRY_TOKEN_VALUE,
                "HOST_GITHUB_TOKEN": _HOST_TOKEN_VALUE,
            },
        )
        entry = _entry(token_env="ENTRY_GITHUB_TOKEN")
        result = adapter.resolve(entry, purpose="api", context=_context())
        assert result.state is ResolutionState.RESOLVED
        assert result.token is not None
        assert result.token.value == _ENTRY_TOKEN_VALUE

    def test_token_env_round_trips_through_load_selector_store(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        document = {
            "version": 1,
            "entries": {"github-work": _environment_entry(tokenEnv="CUSTOM_TOKEN_ENV")},
        }
        _validate_selector_document(document)
        _write_selector(selector, document["entries"])
        loaded = load_selector_store(path=selector, skip_integrity=True)
        assert loaded.entries["github-work"].token_env == "CUSTOM_TOKEN_ENV"

    def test_entry_without_token_env_still_resolves_host_token_env(self, tmp_path: Path) -> None:
        _write_workflow_config(tmp_path, {"provider": "github", "tokenEnv": "HOST_GITHUB_TOKEN"})
        selector = tmp_path / "credential-selector.json"
        _write_selector(selector, {"github-work": _environment_entry()})
        entry = load_selector_store(path=selector, skip_integrity=True).entries["github-work"]
        assert entry.token_env is None
        assert resolve_presence_env_name(entry, root=tmp_path) == "HOST_GITHUB_TOKEN"

        adapter = EnvironmentBackendAdapter(
            repository_root=tmp_path,
            selector_path=selector,
            environ={"HOST_GITHUB_TOKEN": _HOST_TOKEN_VALUE},
        )
        result = adapter.resolve(entry, purpose="api", context=_context())
        assert result.state is ResolutionState.RESOLVED
        assert result.token is not None
        assert result.token.value == _HOST_TOKEN_VALUE

    def test_schema_rejects_secret_valued_property_with_token_env(self) -> None:
        jsonschema = pytest.importorskip("jsonschema")
        schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
        invalid = {
            "version": 1,
            "entries": {
                "github-work": {
                    **_environment_entry(tokenEnv="CUSTOM_TOKEN_ENV"),
                    "token": "must-not-be-here",
                }
            },
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, schema)

    def test_build_selector_entry_writes_token_env_when_supplied(self) -> None:
        entry = build_selector_entry(
            backend="environment",
            provider="github",
            hostname="github.com",
            account="work",
            repo_slug="owner/repo",
            project_id="proj-1",
            token_env="CUSTOM_TOKEN_ENV",
        )
        assert entry["tokenEnv"] == "CUSTOM_TOKEN_ENV"
