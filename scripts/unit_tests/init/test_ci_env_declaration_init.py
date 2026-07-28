"""Init CI env-backend declaration tests (PRD 080 23.4 / R6)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from credentials.ci_declaration import (
    ci_selector_path,
    is_environment_backend_declared,
    load_ci_selector_store,
)
from credentials.environment_backend import EnvironmentBackendAdapter
from credentials.model import ResolutionState
from credentials.resolver import RepositoryContext
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


def _one_account_detector(_root: Path) -> tuple[DetectedAccount, ...]:
    return (
        DetectedAccount(
            provider="github",
            hostname="github.com",
            account="work",
        ),
    )


def _context(project_id: str) -> RepositoryContext:
    return RepositoryContext(
        remote="https://github.com/owner/repo.git",
        repo_slug="owner/repo",
        project_id=project_id,
        destination_endpoint="https://api.github.com/user",
    )


class TestInitOffersCiDeclaration:
    def test_declare_ci_offer_without_write(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        plan = build_init_plan(root, account_detector=_one_account_detector)
        offer = offer_ci_env_declaration(root, plan, confirm=False)
        assert offer["verdict"] == "confirm-required"
        assert "env-backend" in offer["offer"]
        assert not ci_selector_path(root).exists()


class TestCiDeclarationResolvesWithoutLocalSelector:
    def test_fresh_runner_resolves_with_repository_ci_selector(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        plan = build_init_plan(root, account_detector=_one_account_detector)
        config_path = root / ".cursor" / "workflow.config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        from init_credential_migration import credential_refs_patch, merge_config_patch

        config_path.write_text(
            json.dumps(merge_config_patch({}, credential_refs_patch(plan)), indent=2) + "\n",
            encoding="utf-8",
        )
        declared = offer_ci_env_declaration(root, plan, confirm=True)
        assert declared["verdict"] == "ok"
        assert ci_selector_path(root).is_file()
        local_selector = tmp_path / "credential-selector.json"
        assert not local_selector.exists()

        document = load_ci_selector_store(root=root)
        assert "github-work" in document.entries
        assert document.entries["github-work"].backend == "environment"
        assert is_environment_backend_declared(
            "github-work",
            root=root,
            selector_path=local_selector,
        )

        entry = document.entries["github-work"]
        adapter = EnvironmentBackendAdapter(
            repository_root=root,
            selector_path=local_selector,
            environ={"GITHUB_ACTIONS": "true", "GITHUB_TOKEN": _TEST_VALUE},
        )
        result = adapter.resolve(entry, purpose="api", context=_context(plan.project_id))
        assert result.state is ResolutionState.RESOLVED
        assert result.token is not None
        assert result.token.value == _TEST_VALUE

    def test_cli_declare_ci_writes_repository_selector(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        selector = tmp_path / "credential-selector.json"
        plan = build_init_plan(
            root,
            selector_path=selector,
            account_detector=_one_account_detector,
        )
        apply_guided_single_identity(root, plan, confirm=True, selector_path=selector)
        proc = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[2] / "sw-configure.py"),
                "credential",
                "declare-ci",
                "--confirm",
                "--root",
                str(root),
                "--selector-path",
                str(selector),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(proc.stdout)
        assert payload["verdict"] == "ok"
        assert json.loads(ci_selector_path(root).read_text(encoding="utf-8"))["entries"]["github-work"]["backend"] == "environment"
