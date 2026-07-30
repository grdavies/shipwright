"""On-demand credential backend registration (PRD 080 R3 regression).

A committed `credentialRef` must resolve without the caller importing a backend module. Before this
regression guard, only `credentials/doctor.py` imported an adapter module, so host transport, planning
issue-store writes, and memory reads all failed closed with `resolver-unavailable-backend`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from credentials import failure_codes as fc
from credentials.backends import list_backends, load_backend, register_function_name
from credentials.model import CredentialRef, ResolutionState
from credentials.pairing_store import approve_pairing, record_first_use
from credentials.resolver import (
    RepositoryContext,
    _UnavailableBackendAdapter,
    backend_adapter,
    clear_backend_adapters,
    resolve_lookup,
)

_TEST_VALUE = "sk_test_fixture_allowlisted_secret_scan_0123456789"
_REMOTE = "https://github.com/owner/repo.git"


def _entry(backend: str) -> dict[str, object]:
    return {
        "backend": backend,
        "provider": "github",
        "hostname": "github.com",
        "account": "work",
        "allowedRepos": ["owner/repo"],
        "allowedProjectIds": ["proj-1"],
        "allowedEndpoints": ["https://api.github.com"],
    }


def _write_selector(path: Path, entries: dict[str, dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")
    os.chmod(path, 0o600)


def _write_pairing(path: Path, ref: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    record_first_use(ref, "proj-1", _REMOTE, path=path, skip_integrity=True)
    approve_pairing(ref, "proj-1", _REMOTE, path=path, skip_integrity=True)


def _context() -> RepositoryContext:
    return RepositoryContext(
        remote=_REMOTE,
        repo_slug="owner/repo",
        project_id="proj-1",
        destination_endpoint="https://api.github.com/user",
    )


def _write_repo_config(root: Path, *, ref: str) -> None:
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    (root / ".cursor" / "workflow.config.json").write_text(
        json.dumps(
            {
                "projectId": "proj-1",
                "host": {"provider": "github", "remote": "origin", "credentialRef": ref, "tokenEnv": "TEST_HOST_TOKEN"},
            }
        ),
        encoding="utf-8",
    )
    (root / ".sw").mkdir(parents=True, exist_ok=True)
    (root / ".sw" / "credential-ci-selector.json").write_text(
        json.dumps({"version": 1, "entries": {ref: _entry("environment")}}),
        encoding="utf-8",
    )


@pytest.fixture(autouse=True)
def _isolate_backend_adapters() -> None:
    clear_backend_adapters(disable_lazy=False)
    yield
    clear_backend_adapters()


class TestOnDemandRegistration:
    def test_every_backend_exposes_a_register_entry_point(self) -> None:
        for backend in list_backends():
            load_backend(backend)()
            assert not isinstance(backend_adapter(backend), _UnavailableBackendAdapter)

    def test_register_entry_point_names_follow_convention(self) -> None:
        assert register_function_name("environment") == "register_environment_backend"
        assert register_function_name("github_cli") == "register_github_cli_backend"

    def test_unknown_backend_stays_unavailable(self) -> None:
        assert isinstance(backend_adapter("no-such-backend"), _UnavailableBackendAdapter)

    def test_credential_ref_resolves_without_caller_importing_a_backend(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _write_repo_config(root, ref="github-work")
        selector = tmp_path / "config" / "credential-selector.json"
        pairing = tmp_path / "config" / "credential-pairings.json"
        _write_selector(selector, {"github-work": _entry("environment")})
        _write_pairing(pairing, "github-work")
        monkeypatch.setenv("TEST_HOST_TOKEN", _TEST_VALUE)
        monkeypatch.chdir(root)

        result = resolve_lookup(
            CredentialRef("github-work"),
            provider="github",
            purpose="host",
            context=_context(),
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
        )

        assert result.failure_code != fc.UNAVAILABLE_BACKEND
        assert result.resolution.state is ResolutionState.RESOLVED
        assert result.backend == "environment"


class TestClearedRegistryStaysCleared:
    def test_cleared_registry_refuses_lazy_registration(self, tmp_path: Path) -> None:
        clear_backend_adapters()
        selector = tmp_path / "config" / "credential-selector.json"
        pairing = tmp_path / "config" / "credential-pairings.json"
        _write_selector(selector, {"github-work": _entry("environment")})
        _write_pairing(pairing, "github-work")

        result = resolve_lookup(
            CredentialRef("github-work"),
            provider="github",
            purpose="host",
            context=_context(),
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
        )

        assert result.resolution.state is ResolutionState.UNRESOLVED
        assert result.failure_code == fc.UNAVAILABLE_BACKEND
