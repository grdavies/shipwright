"""GH_CONFIG_DIR concurrency tests for github_cli backend (PRD 080 8.3 / R5)."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from credentials.child_env import GH_CONFIG_DIR_ENV
from credentials.github_cli_backend import (
    GithubCliBackendAdapter,
    GithubCliInvocation,
    broker_gh_config_dir,
)
from credentials.model import ResolutionState
from credentials.resolver import RepositoryContext
from credentials.selector_store import SelectorEntry

_TEST_VALUE = "sk_test_fixture_allowlisted_secret_scan_0123456789"


def _entry(ref: str, account: str) -> SelectorEntry:
    return SelectorEntry(
        ref=ref,
        backend="github_cli",
        provider="github",
        hostname="github.com",
        account=account,
        allowed_repos=("owner/repo",),
        allowed_project_ids=("proj-1",),
        allowed_endpoints=("https://api.github.com",),
    )


def _context() -> RepositoryContext:
    return RepositoryContext(
        remote="https://github.com/owner/repo.git",
        repo_slug="owner/repo",
        project_id="proj-1",
        destination_endpoint="https://api.github.com/user",
    )


class TestGhConfigDirConcurrency:
    def test_interleaved_references_use_distinct_config_dirs(self, tmp_path: Path) -> None:
        observed: list[tuple[str, str, str]] = []
        lock = threading.Lock()
        barrier = threading.Barrier(2)

        def _runner_factory(ref_hint: str) -> object:
            def _runner(invocation: GithubCliInvocation) -> subprocess.CompletedProcess[str]:
                config_dir = invocation.env[GH_CONFIG_DIR_ENV]
                with lock:
                    observed.append((ref_hint, config_dir, invocation.argv[-1]))
                barrier.wait(timeout=5)
                if invocation.argv[-1] == "token":
                    return subprocess.CompletedProcess(
                        args=list(invocation.argv),
                        returncode=0,
                        stdout=f"{_TEST_VALUE}\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(
                    args=list(invocation.argv),
                    returncode=0,
                    stdout="github.com\n  Token scopes: 'repo, read:user'\n",
                    stderr="",
                )

            return _runner

        adapter_a = GithubCliBackendAdapter(
            runner=_runner_factory("ref-a"),
            gh_executable="/usr/bin/gh",
            broker_root=tmp_path,
            work_dir=tmp_path,
        )
        adapter_b = GithubCliBackendAdapter(
            runner=_runner_factory("ref-b"),
            gh_executable="/usr/bin/gh",
            broker_root=tmp_path,
            work_dir=tmp_path,
        )

        results: list[object] = []

        def _resolve(adapter: GithubCliBackendAdapter, entry: SelectorEntry) -> None:
            results.append(adapter.resolve(entry, purpose="api", context=_context()))

        thread_a = threading.Thread(
            target=_resolve,
            args=(adapter_a, _entry("ref-a", "account-a")),
        )
        thread_b = threading.Thread(
            target=_resolve,
            args=(adapter_b, _entry("ref-b", "account-b")),
        )
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)

        assert len(results) == 2
        assert all(result.state is ResolutionState.RESOLVED for result in results)  # type: ignore[attr-defined]

        dir_a = broker_gh_config_dir(ref="ref-a", broker_root=tmp_path).resolve()
        dir_b = broker_gh_config_dir(ref="ref-b", broker_root=tmp_path).resolve()
        config_dirs = {dir_a, dir_b}
        assert dir_a != dir_b

        token_dirs = [item[1] for item in observed if item[2] == "token"]
        assert len(token_dirs) == 2
        assert len(set(token_dirs)) == 2
        assert all(Path(path).resolve() in config_dirs for path in token_dirs)

        by_ref = {ref: {config for ref_name, config, _ in observed if ref_name == ref} for ref in ("ref-a", "ref-b")}
        assert len(by_ref["ref-a"]) == 1
        assert len(by_ref["ref-b"]) == 1
        assert by_ref["ref-a"] != by_ref["ref-b"]
