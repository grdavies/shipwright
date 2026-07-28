"""Scope-enforcement negative tests for the credential resolver (PRD 080 5.3 / R3)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from credentials import failure_codes as fc
from credentials.model import CredentialRef
from credentials.pairing_store import approve_pairing, record_first_use
from credentials.resolver import RepositoryContext, resolve_lookup
from credentials.selector_store import SelectorStoreError, load_selector_store


def _valid_entry(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "backend": "github_cli",
        "provider": "github",
        "hostname": "github.com",
        "account": "work",
        "allowedRepos": ["owner/repo"],
        "allowedProjectIds": ["proj-1"],
        "allowedEndpoints": ["https://api.github.com"],
    }
    payload.update(overrides)
    return payload


def _write_selector(path: Path, entries: dict[str, dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")
    os.chmod(path, 0o600)


def _write_pairing(path: Path, ref: str, project_id: str, remote: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    record_first_use(ref, project_id, remote, path=path, skip_integrity=True)
    approve_pairing(ref, project_id, remote, path=path, skip_integrity=True)


def _context(
    *,
    remote: str = "https://github.com/owner/repo.git",
    repo_slug: str = "owner/repo",
    project_id: str = "proj-1",
    destination_endpoint: str = "https://api.github.com/user",
) -> RepositoryContext:
    return RepositoryContext(
        remote=remote,
        repo_slug=repo_slug,
        project_id=project_id,
        destination_endpoint=destination_endpoint,
    )


class TestRemoteOutsideAllowedRepos:
    def test_remote_outside_allowed_repos_fails_closed(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        pairing = tmp_path / "credential-pairings.json"
        _write_selector(selector, {"github-work": _valid_entry(allowedRepos=["other/repo"])})
        _write_pairing(pairing, "github-work", "proj-1", "https://github.com/owner/repo.git")

        result = resolve_lookup(
            CredentialRef("github-work"),
            provider="github",
            purpose="api",
            context=_context(),
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
        )

        assert result.failure_code == fc.OUT_OF_SCOPE_REPO
        assert result.resolution.state.value == "unresolved"


class TestProjectOutsideAllowedProjectIds:
    def test_project_id_outside_allowed_project_ids_fails_closed(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        pairing = tmp_path / "credential-pairings.json"
        _write_selector(selector, {"github-work": _valid_entry(allowedProjectIds=["proj-other"])})
        _write_pairing(pairing, "github-work", "proj-1", "https://github.com/owner/repo.git")

        result = resolve_lookup(
            CredentialRef("github-work"),
            provider="github",
            purpose="api",
            context=_context(project_id="proj-1"),
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
        )

        assert result.failure_code == fc.OUT_OF_SCOPE_PROJECT
        assert result.resolution.state.value == "unresolved"


class TestEndpointOutsideAllowedEndpoints:
    def test_endpoint_outside_allowed_endpoints_fails_closed(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        pairing = tmp_path / "credential-pairings.json"
        _write_selector(
            selector,
            {"github-work": _valid_entry(allowedEndpoints=["https://api.github.com"])},
        )
        _write_pairing(pairing, "github-work", "proj-1", "https://github.com/owner/repo.git")

        result = resolve_lookup(
            CredentialRef("github-work"),
            provider="github",
            purpose="api",
            context=_context(destination_endpoint="https://evil.example.com/user"),
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
        )

        assert result.failure_code == fc.OUT_OF_SCOPE_ENDPOINT
        assert result.resolution.state.value == "unresolved"


class TestMissingMandatoryScopeField:
    @pytest.mark.parametrize(
        ("field", "code"),
        [
            ("allowedRepos", "selector-missing-allowed-repos"),
            ("allowedProjectIds", "selector-missing-allowed-project-ids"),
            ("allowedEndpoints", "selector-missing-allowed-endpoints"),
        ],
    )
    def test_missing_scope_field_fails_closed_at_load(
        self,
        tmp_path: Path,
        field: str,
        code: str,
    ) -> None:
        selector = tmp_path / "credential-selector.json"
        entry = _valid_entry()
        entry.pop(field)
        _write_selector(selector, {"github-work": entry})

        with pytest.raises(SelectorStoreError) as exc:
            load_selector_store(path=selector, skip_integrity=True)
        assert exc.value.code == code

        result = resolve_lookup(
            CredentialRef("github-work"),
            provider="github",
            purpose="api",
            context=_context(),
            selector_path=selector,
            pairing_path=tmp_path / "credential-pairings.json",
            skip_integrity=True,
        )
        assert result.failure_code == fc.INSUFFICIENT_SCOPE
