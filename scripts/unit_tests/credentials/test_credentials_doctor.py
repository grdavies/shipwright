"""Credential doctor failure-code tests (PRD 080 22.3 / R7) — Z,O,M,E,I."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from credentials import failure_codes as fc
from credentials.doctor import (
    CREDENTIAL_DOCTOR_CLI,
    diagnose_repository,
    diagnose_surface,
    list_known_references,
    remediation_for_code,
    remediate,
)
from credentials.config_surface import resolve_config_surface
from credentials.model import Principal, ResolutionState, Secret
from credentials.pairing_store import approve_pairing, record_first_use
from credentials.resolver import BackendResolveResult, register_backend_adapter

_TEST_VALUE = "sk_test_fixture_allowlisted_secret_scan_0123456789"


class _HealthyBackend:
    def resolve(self, entry, **kwargs):  # noqa: ANN001
        return BackendResolveResult(
            state=ResolutionState.RESOLVED,
            token=Secret("broker-fixture-token"),
            principal=Principal(profile="work", account="work"),
            backend=entry.backend,
        )


def _valid_entry(**overrides: object) -> dict[str, object]:
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


def _write_config(root: Path, **overrides: object) -> None:
    cfg: dict[str, object] = {
        "projectId": "proj-1",
        "host": {
            "provider": "github",
            "credentialRef": "github-work",
        },
    }
    cfg.update(overrides)
    path = root / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg), encoding="utf-8")


def _context() -> RepositoryContext:
    return RepositoryContext(
        remote="https://github.com/owner/repo.git",
        repo_slug="owner/repo",
        project_id="proj-1",
        destination_endpoint="https://api.github.com/user",
    )


class TestNoSelector:
    def test_missing_selector_reports_stable_code_and_one_local_remediation(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _write_config(root)
        missing_selector = tmp_path / "missing" / "credential-selector.json"
        report = diagnose_repository(root, selector_path=missing_selector, skip_integrity=True)
        assert report["verdict"] == "fail"
        host_surface = report["surfaces"][0]
        assert host_surface["failure"]["code"] == fc.MISSING_SELECTOR
        assert host_surface["failure"]["remediationScope"] == "local"
        assert host_surface["failure"]["remediationCommand"].count("remediate") == 1
        remediation = remediation_for_code(fc.MISSING_SELECTOR, root=root)
        assert remediation.scope == "local"
        assert remediation.command.startswith(CREDENTIAL_DOCTOR_CLI)


def _init_git_remote(root: Path, slug: str = "owner/repo") -> str:
    remote = f"https://github.com/{slug}.git"
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=root, check=True)
    return remote


class TestOneHealthyReference:
    def test_one_healthy_reference_passes_required_operation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        _write_config(root)
        selector = tmp_path / "credential-selector.json"
        pairing = tmp_path / "credential-pairings.json"
        _write_selector(selector, {"github-work": _valid_entry()})
        _write_pairing(pairing, "github-work", "proj-1", "https://github.com/owner/repo.git")

        register_backend_adapter("environment", _HealthyBackend())

        report = diagnose_repository(
            root,
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
            register_env_backend=False,
        )
        assert report["verdict"] == "ok"
        host_surface = report["surfaces"][0]
        assert host_surface["requiredOperationVerdict"] == "pass"
        assert host_surface["resolvedPrincipal"] == {"profile": "work", "account": "work"}
        refs = list_known_references(selector_path=selector, skip_integrity=True)
        assert len(refs) == 1
        assert refs[0].last_successful_resolution is not None


class TestManyReferences:
    def test_many_references_listed_with_backends_and_scopes(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        entries = {
            "github-work": _valid_entry(account="alice"),
            "github-personal": _valid_entry(account="bob", allowedProjectIds=["proj-2"]),
            "github-ci": _valid_entry(backend="github_cli", account="ci-bot"),
        }
        _write_selector(selector, entries)
        refs = list_known_references(selector_path=selector, skip_integrity=True)
        assert len(refs) == 3
        backends = {item.ref: item.backend for item in refs}
        assert backends["github-work"] == "environment"
        assert backends["github-ci"] == "github_cli"
        principals = {item.ref: item.principal for item in refs}
        assert principals["github-work"]["account"] == "alice"
        assert principals["github-personal"]["account"] == "bob"


class TestEnumeratedFailureCauses:
    @pytest.mark.parametrize(
        "code",
        list(fc.ALL_FAILURE_CODES),
    )
    def test_each_failure_code_maps_to_one_remediation_command(
        self, tmp_path: Path, code: str
    ) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        remediation = remediation_for_code(code, root=root)
        assert remediation.scope in {"local", "ci"}
        assert remediation.command.count("remediate") == 1
        assert remediation.command.startswith(CREDENTIAL_DOCTOR_CLI)

    def test_unknown_ref_failure_has_stable_code(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _write_config(root, host={"provider": "github", "credentialRef": "missing-ref"})
        selector = tmp_path / "credential-selector.json"
        _write_selector(selector, {"github-work": _valid_entry()})
        pairing = tmp_path / "credential-pairings.json"
        _write_pairing(pairing, "missing-ref", "proj-1", "https://github.com/owner/repo.git")

        report = diagnose_repository(
            root,
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
        )
        failure = report["surfaces"][0]["failure"]
        assert failure["code"] == fc.UNKNOWN_REF

    def test_out_of_scope_repo_failure(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        _write_config(root)
        selector = tmp_path / "credential-selector.json"
        _write_selector(selector, {"github-work": _valid_entry(allowedRepos=["other/repo"])})
        pairing = tmp_path / "credential-pairings.json"
        _write_pairing(pairing, "github-work", "proj-1", "https://github.com/owner/repo.git")

        report = diagnose_repository(
            root,
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
        )
        assert report["surfaces"][0]["failure"]["code"] == fc.OUT_OF_SCOPE_REPO

    def test_remediate_writes_local_selector_template(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        selector = tmp_path / "credential-selector.json"
        result = remediate(
            scope="local",
            code=fc.MISSING_SELECTOR,
            root=root,
            selector_path=selector,
        )
        assert result["verdict"] == "ok"
        selector_path = Path(result["path"])
        assert selector_path == selector
        payload = json.loads(selector_path.read_text(encoding="utf-8"))
        assert payload["version"] == 1
        assert "entries" in payload


class TestIsolationNoSecretValues:
    def test_diagnosis_never_contains_token_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        _write_config(root)
        selector = tmp_path / "credential-selector.json"
        pairing = tmp_path / "credential-pairings.json"
        _write_selector(selector, {"github-work": _valid_entry()})
        _write_pairing(pairing, "github-work", "proj-1", "https://github.com/owner/repo.git")
        register_backend_adapter("environment", _HealthyBackend())
        report = diagnose_repository(
            root,
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
            register_env_backend=False,
        )
        serialized = json.dumps(report)
        assert _TEST_VALUE not in serialized
        assert "sk_test" not in serialized
