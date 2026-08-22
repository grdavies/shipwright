"""Credential doctor checklist alignment tests (PRD 324 phase 2 / R1, R2, R4)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from credentials import failure_codes as fc
from credentials.checklist import CHECKLIST_STEP_ORDER
from credentials.doctor import CREDENTIAL_DOCTOR_CLI, diagnose_repository
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


def _init_git_remote(root: Path, slug: str = "owner/repo") -> str:
    remote = f"https://github.com/{slug}.git"
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=root, check=True)
    return remote


class TestChecklistShape:
    def test_reports_four_ordered_checklist_steps(self, tmp_path: Path) -> None:
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
        checklist = report["checklist"]
        assert [item["step"] for item in checklist] == list(CHECKLIST_STEP_ORDER)
        assert all(item["verdict"] in {"pass", "fail"} for item in checklist)
        assert all(item.get("remediationCommand") or item["verdict"] == "pass" for item in checklist)


class TestUndeclaredAmbientToken:
    def test_ambient_github_token_without_declaration_never_green(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        _write_config(root, host={"provider": "github", "tokenEnv": "GITHUB_TOKEN"})
        monkeypatch.setenv("GITHUB_TOKEN", _TEST_VALUE)

        report = diagnose_repository(
            root,
            selector_path=tmp_path / "missing-selector.json",
            skip_integrity=True,
            environ={"GITHUB_TOKEN": _TEST_VALUE},
            register_env_backend=False,
        )
        assert report["verdict"] == "fail"
        identity = report["checklist"][0]
        assert identity["step"] == "identity-source"
        assert identity["verdict"] == "fail"
        assert "undeclared-ambient-token" in identity["cause"]
        assert "GITHUB_TOKEN" in identity["cause"]
        assert identity["remediationCommand"]
        assert report["surfaces"][0]["requiredOperationVerdict"] == "fail"
        assert report["surfaces"][0]["failure"]["code"] == fc.MISSING_CI_DECLARATION

    def test_named_token_env_with_declared_backend_resolves_green(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        token_env = "SW_GITHUB_TOKEN_WORK"
        _write_config(
            root,
            host={
                "provider": "github",
                "credentialRef": "github-work",
            },
        )
        selector = tmp_path / "credential-selector.json"
        pairing = tmp_path / "credential-pairings.json"
        _write_selector(
            selector,
            {
                "github-work": _valid_entry(
                    tokenEnv=token_env,
                )
            },
        )
        _write_pairing(pairing, "github-work", "proj-1", "https://github.com/owner/repo.git")
        register_backend_adapter("environment", _HealthyBackend())

        report = diagnose_repository(
            root,
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
            environ={token_env: _TEST_VALUE},
            register_env_backend=False,
        )
        assert report["verdict"] == "ok"
        assert all(step["verdict"] == "pass" for step in report["checklist"])


class TestChecklistRemediationCommands:
    def test_failing_step_includes_typed_cause_and_remediation(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _write_config(root)
        report = diagnose_repository(
            root,
            selector_path=tmp_path / "missing-selector.json",
            skip_integrity=True,
        )
        failing = [step for step in report["checklist"] if step["verdict"] == "fail"]
        assert failing
        for step in failing:
            assert step["cause"]
            assert step["remediationCommand"]
            assert CREDENTIAL_DOCTOR_CLI.split()[0] in step["remediationCommand"] or (
                "sw-configure.py" in step["remediationCommand"]
            )
