"""GitHub CLI backend tests with a stubbed CLI (PRD 080 8.2 / R5)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from credentials import failure_codes as fc
from credentials.child_env import GH_CONFIG_DIR_ENV, GH_HOST_ENV
from credentials.github_cli_backend import (
    GITHUB_CLI_ENFORCEABILITY,
    GithubCliBackendAdapter,
    GithubCliInvocation,
    build_github_cli_child_env,
    build_github_cli_probe_env,
    enforceability_statement,
    parse_scopes_from_auth_status,
    probe_scopes,
    register_github_cli_backend,
    resolve_credential_env_name,
)
from credentials.model import ResolutionState
from credentials.resolver import RepositoryContext, clear_backend_adapters
from credentials.selector_store import SelectorEntry

_TEST_VALUE = "sk_test_fixture_allowlisted_secret_scan_0123456789"


def _entry(**overrides: object) -> SelectorEntry:
    payload: dict[str, object] = {
        "ref": "github-work",
        "backend": "github_cli",
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


def _success_runner(token: str = _TEST_VALUE, scopes: str = "repo, read:user") -> object:
    def _runner(invocation: GithubCliInvocation) -> subprocess.CompletedProcess[str]:
        if invocation.argv[-1] == "token":
            return subprocess.CompletedProcess(
                args=list(invocation.argv),
                returncode=0,
                stdout=f"{token}\n",
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=list(invocation.argv),
            returncode=0,
            stdout=f"github.com\n  Token scopes: '{scopes}'\n",
            stderr="",
        )

    return _runner


@pytest.fixture(autouse=True)
def _reset_backend_adapters() -> None:
    clear_backend_adapters()
    register_github_cli_backend()
    yield
    clear_backend_adapters()


class TestEnforceabilityStatement:
    def test_publishes_scope_probe_and_isolation(self) -> None:
        statement = enforceability_statement()
        assert statement is GITHUB_CLI_ENFORCEABILITY
        assert statement.isolation_key == GH_CONFIG_DIR_ENV
        assert statement.scope_probe_command == "gh auth status"
        assert statement.prohibits_account_switch is True
        assert statement.credential_env_name == resolve_credential_env_name(_entry())


class TestScopeParsing:
    def test_parse_scopes_from_auth_status(self) -> None:
        stdout = "github.com\n  ✓ Logged in\n  - Token scopes: 'repo, read:org'\n"
        assert parse_scopes_from_auth_status(stdout) == ("repo", "read:org")

    def test_scope_shortfall_surfaces_missing_requirement(self) -> None:
        result = probe_scopes(("read:user",), ("repo", "read:user"))
        assert result.shortfall == ("repo",)
        assert not result.sufficient


class TestGithubCliChildEnv:
    def test_probe_env_sets_broker_controlled_gh_keys(self) -> None:
        env = build_github_cli_probe_env(
            {"GH_CONFIG_DIR": "/parent/config", GH_HOST_ENV: "parent.example.com"},
            gh_host="github.com",
            gh_config_dir="/broker/gh-config",
        )
        assert env[GH_CONFIG_DIR_ENV] == "/broker/gh-config"
        assert env[GH_HOST_ENV] == "github.com"
        assert env["GH_PROMPT_DISABLED"] == "1"
        assert "GITHUB_TOKEN" not in env

    def test_child_env_resupplies_exactly_one_credential_variable(self, tmp_path: Path) -> None:
        entry = _entry()
        env = build_github_cli_child_env(
            {"GITHUB_TOKEN": "parent-token", "GH_TOKEN": "parent-gh"},
            entry=entry,
            gh_host="github.com",
            gh_config_dir=str(tmp_path),
            credential_env_value=_TEST_VALUE,
        )
        assert env["GH_TOKEN"] == _TEST_VALUE
        assert "GITHUB_TOKEN" not in env
        assert env[GH_CONFIG_DIR_ENV] == str(tmp_path.resolve())


class TestGithubCliBackendAdapter:
    def test_missing_cli_fails_closed(self, tmp_path: Path) -> None:
        adapter = GithubCliBackendAdapter(
            gh_executable="",
            broker_root=tmp_path,
            work_dir=tmp_path,
        )
        result = adapter.resolve(_entry(), purpose="api", context=_context())
        assert result.state is ResolutionState.UNRESOLVED
        assert result.failure_code == fc.UNAVAILABLE_BACKEND

    def test_one_configured_reference_resolves_with_stubbed_cli(self, tmp_path: Path) -> None:
        calls: list[GithubCliInvocation] = []

        def _runner(invocation: GithubCliInvocation) -> subprocess.CompletedProcess[str]:
            calls.append(invocation)
            return _success_runner()(invocation)

        adapter = GithubCliBackendAdapter(
            runner=_runner,
            gh_executable="/usr/bin/gh",
            broker_root=tmp_path,
            work_dir=tmp_path,
        )
        entry = _entry()
        result = adapter.resolve(entry, purpose="api", context=_context())
        assert result.state is ResolutionState.RESOLVED
        assert result.token is not None
        assert result.token.value == _TEST_VALUE
        assert len(calls) == 2
        assert calls[0].argv[-1] == "token"
        assert calls[1].argv[-2:] == ("auth", "status")
        assert calls[0].env[GH_CONFIG_DIR_ENV] == calls[1].env[GH_CONFIG_DIR_ENV]
        assert calls[0].env[GH_CONFIG_DIR_ENV] != "/parent/config"
        assert calls[0].env["GH_PROMPT_DISABLED"] == "1"

    def test_scope_shortfall_fails_closed(self, tmp_path: Path) -> None:
        adapter = GithubCliBackendAdapter(
            runner=_success_runner(scopes="read:user"),
            gh_executable="/usr/bin/gh",
            broker_root=tmp_path,
            work_dir=tmp_path,
        )
        result = adapter.resolve(_entry(), purpose="api", context=_context())
        assert result.state is ResolutionState.UNRESOLVED
        assert result.failure_code == fc.INSUFFICIENT_SCOPE

    def test_no_account_switch_subcommand_in_backend_source(self) -> None:
        source = (
            Path(__file__).resolve().parents[2]
            / "credentials"
            / "github_cli_backend.py"
        ).read_text(encoding="utf-8")
        assert "auth switch" not in source
        assert "auth-switch" not in source
