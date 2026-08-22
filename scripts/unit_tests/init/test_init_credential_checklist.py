"""Credential checklist model tests (PRD 324 phase 1 / R1, R2, R4)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from init_credential_migration import (
    CHECKLIST_STEP_ORDER,
    DetectedAccount,
    apply_guided_single_identity,
    build_credential_checklist,
    build_init_plan,
    detect_multi_account_risk,
    offer_example_env_file,
    suggest_named_token_env,
)


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


def _many_accounts_detector(_root: Path) -> tuple[DetectedAccount, ...]:
    return (
        DetectedAccount(provider="github", hostname="github.com", account="work"),
        DetectedAccount(provider="github", hostname="github.com", account="personal"),
    )


def _no_accounts_detector(_root: Path) -> tuple[DetectedAccount, ...]:
    return ()


class TestCredentialChecklist:
    def test_checklist_emitted_once_in_fixed_order(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        plan = build_init_plan(root, account_detector=_one_account_detector)
        checklist = build_credential_checklist(root, plan)
        step_ids = tuple(step.id for step in checklist.steps)
        assert step_ids == CHECKLIST_STEP_ORDER
        assert len(checklist.steps) == 4

    def test_github_cli_default_when_authenticated(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        selector = tmp_path / "credential-selector.json"
        plan = build_init_plan(root, selector_path=selector, account_detector=_one_account_detector)
        result = apply_guided_single_identity(
            root,
            plan,
            confirm=True,
            selector_path=selector,
        )
        assert result["verdict"] == "ok"
        document = json.loads(selector.read_text(encoding="utf-8"))
        assert document["entries"]["github-work"]["backend"] == "github_cli"
        assert "namedTokenEnv" not in result

    def test_named_token_env_offered_under_multi_account_fixture(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        selector = tmp_path / "credential-selector.json"
        plan = build_init_plan(root, selector_path=selector, account_detector=_many_accounts_detector)
        risk = detect_multi_account_risk(root, plan, selector_path=selector)
        assert risk["risk"] is True
        assert risk["namedTokenEnv"] == suggest_named_token_env("github", "work")
        dry = apply_guided_single_identity(
            root,
            plan,
            confirm=False,
            selector_path=selector,
        )
        assert dry["verdict"] == "halt"
        assert dry["namedTokenEnv"] == suggest_named_token_env("github", "work")

    def test_named_token_env_not_offered_under_single_account(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        selector = tmp_path / "credential-selector.json"
        plan = build_init_plan(root, selector_path=selector, account_detector=_one_account_detector)
        risk = detect_multi_account_risk(root, plan, selector_path=selector)
        assert risk["risk"] is False
        assert risk["namedTokenEnv"] is None

    def test_selector_never_receives_token_material(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        selector = tmp_path / "credential-selector.json"
        plan = build_init_plan(root, selector_path=selector, account_detector=_one_account_detector)
        result = apply_guided_single_identity(
            root,
            plan,
            confirm=True,
            selector_path=selector,
        )
        serialized = json.dumps(result) + selector.read_text(encoding="utf-8")
        assert "ghp_" not in serialized
        assert "github_pat_" not in serialized
        entry = json.loads(selector.read_text(encoding="utf-8"))["entries"]["github-work"]
        assert "token" not in "".join(entry.keys()).lower() or entry.get("tokenEnv")

    def test_no_env_created_on_primary_path(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        selector = tmp_path / "credential-selector.json"
        plan = build_init_plan(root, selector_path=selector, account_detector=_no_accounts_detector)
        apply_guided_single_identity(root, plan, confirm=True, selector_path=selector)
        assert not (root / ".env").exists()
        assert not (root / ".env.example").exists()

    def test_example_env_written_only_on_explicit_request(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        dry = offer_example_env_file(root, token_env="SW_GITHUB_TOKEN_WORK", confirm=False)
        assert dry["verdict"] == "confirm-required"
        assert not (root / ".env.example").exists()
        applied = offer_example_env_file(root, token_env="SW_GITHUB_TOKEN_WORK", confirm=True)
        assert applied["verdict"] == "ok"
        assert (root / ".env.example").is_file()
        assert ".env.example" in (root / ".gitignore").read_text(encoding="utf-8")

    def test_checklist_cli_entrypoint(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        _init_git_remote(root)
        proc = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[2] / "sw-configure.py"),
                "credential",
                "checklist",
                "--root",
                str(root),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        payload = json.loads(proc.stdout)
        assert [step["id"] for step in payload["steps"]] == list(CHECKLIST_STEP_ORDER)
