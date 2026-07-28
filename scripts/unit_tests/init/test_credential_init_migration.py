"""Init credential migration tests (PRD 080 23.3 / R1, R2)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from credentials.selector_store import load_selector_store
from init_credential_migration import (
    CONFIGURE_CLI,
    DetectedAccount,
    apply_guided_single_identity,
    build_init_plan,
    migration_selector_command,
    offer_legacy_migration,
    selector_add_command,
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


def _many_accounts_detector(_root: Path) -> tuple[DetectedAccount, ...]:
    return (
        DetectedAccount(provider="github", hostname="github.com", account="work"),
        DetectedAccount(provider="github", hostname="github.com", account="personal"),
    )


def _no_accounts_detector(_root: Path) -> tuple[DetectedAccount, ...]:
    return ()


class TestGreenfieldRepository:
    def test_guided_path_writes_config_and_selector(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        selector = tmp_path / "credential-selector.json"
        plan = build_init_plan(
            root,
            selector_path=selector,
            account_detector=_no_accounts_detector,
        )
        result = apply_guided_single_identity(
            root,
            plan,
            confirm=True,
            selector_path=selector,
        )
        assert result["verdict"] == "ok"
        cfg = json.loads((root / ".cursor" / "workflow.config.json").read_text(encoding="utf-8"))
        assert cfg["projectId"] == "repo"
        assert cfg["host"]["credentialRef"] == "github-work"
        assert cfg["planning"]["store"]["issues"]["credentialRef"] == "planning-work"
        assert cfg["memory"]["credentialRef"] == "memory-work"
        document = load_selector_store(path=selector, skip_integrity=True)
        assert "github-work" in document.entries
        assert document.entries["github-work"].backend == "environment"


class TestOneDetectedAccount:
    def test_guided_path_uses_github_cli_backend(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        selector = tmp_path / "credential-selector.json"
        plan = build_init_plan(
            root,
            selector_path=selector,
            account_detector=_one_account_detector,
        )
        assert plan.disclosure == "single"
        result = apply_guided_single_identity(
            root,
            plan,
            confirm=True,
            selector_path=selector,
        )
        assert result["verdict"] == "ok"
        document = load_selector_store(path=selector, skip_integrity=True)
        assert document.entries["github-work"].backend == "github_cli"
        assert document.entries["github-work"].account == "work"


class TestManyDetectedAccounts:
    def test_progressive_disclosure_halts_guided_apply(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        selector = tmp_path / "credential-selector.json"
        plan = build_init_plan(
            root,
            selector_path=selector,
            account_detector=_many_accounts_detector,
        )
        assert plan.disclosure == "multi"
        result = apply_guided_single_identity(
            root,
            plan,
            confirm=True,
            selector_path=selector,
        )
        assert result["verdict"] == "halt"
        assert "keystore" in result["hint"]
        assert not (root / ".cursor" / "workflow.config.json").exists()
        assert not selector.exists()


class TestLegacyTokenVariableRepository:
    def test_migration_prints_exact_selector_command(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        _write_config(
            root,
            {
                "host": {
                    "provider": "github",
                    "remote": "origin",
                    "tokenEnv": "GITHUB_TOKEN",
                }
            },
        )
        selector = tmp_path / "credential-selector.json"
        plan = build_init_plan(
            root,
            selector_path=selector,
            account_detector=_one_account_detector,
        )
        dry = offer_legacy_migration(root, plan, confirm=False, selector_path=selector)
        expected = selector_add_command(
            ref="github-work",
            backend="environment",
            provider="github",
            hostname="github.com",
            account="work",
            repo_slug="owner/repo",
            project_id=plan.project_id,
        )
        assert dry["selectorCommand"] == expected
        assert dry["selectorCommand"] == migration_selector_command(plan)

        applied = offer_legacy_migration(root, plan, confirm=True, selector_path=selector)
        assert applied["verdict"] == "ok"
        cfg = json.loads((root / ".cursor" / "workflow.config.json").read_text(encoding="utf-8"))
        assert cfg["host"]["credentialRef"] == "github-work"
        assert cfg["host"]["tokenEnv"] == "GITHUB_TOKEN"
        document = load_selector_store(path=selector, skip_integrity=True)
        assert "github-work" in document.entries

    def test_cli_migrate_emits_selector_command(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        _write_config(
            root,
            {
                "host": {
                    "provider": "github",
                    "remote": "origin",
                    "tokenEnv": "GITHUB_TOKEN",
                }
            },
        )
        selector = tmp_path / "credential-selector.json"
        proc = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[2] / "sw-configure.py"),
                "credential",
                "migrate",
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
        assert payload["verdict"] == "confirm-required"
        assert payload["selectorCommand"].startswith(f"{CONFIGURE_CLI} credential selector-add ")


class TestNoSecretsPrinted:
    def test_migration_output_never_contains_token_value(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        _write_config(
            root,
            {
                "host": {
                    "provider": "github",
                    "remote": "origin",
                    "tokenEnv": "GITHUB_TOKEN",
                }
            },
        )
        os.environ["GITHUB_TOKEN"] = _TEST_VALUE
        plan = build_init_plan(root, account_detector=_one_account_detector)
        dry = offer_legacy_migration(root, plan, confirm=False)
        serialized = json.dumps(dry)
        assert _TEST_VALUE not in serialized
        assert "sk_test" not in serialized
