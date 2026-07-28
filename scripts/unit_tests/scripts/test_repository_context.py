"""RepositoryContext construction and invariant tests (PRD 080 12.3 / R9)."""

from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from repository_context import (
    CONTEXT_ENVELOPE_ENV,
    RepositoryContext,
    RepositoryContextError,
    RootInvariantError,
    from_envelope,
    from_root,
    parse_envelope,
)


def _write_workflow_config(repo: Path, *, project: str = "fixture-project") -> None:
    cursor = repo / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    payload = {
        "host": {"provider": "github", "remote": "origin"},
        "memory": {"provider": "recallium", "project": project},
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
            }
        },
        "orchestration": {"planPolicy": "proposed"},
    }
    (cursor / "workflow.config.json").write_text(json.dumps(payload), encoding="utf-8")


def _seed_repo(repo: Path, *, worktree_name: str | None = None) -> None:
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/demo.git"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    _write_workflow_config(repo)
    if worktree_name:
        state = repo / ".cursor" / "sw-worktree-state.json"
        state.write_text(json.dumps({"worktreeName": worktree_name}), encoding="utf-8")


class TestAbsentRoot:
    def test_missing_root_fails_closed(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing"
        with pytest.raises(RepositoryContextError, match="not a directory"):
            from_root(missing)


class TestOneValidRoot:
    def test_from_root_builds_explicit_context(self, tmp_git_repo: Path) -> None:
        _seed_repo(tmp_git_repo, worktree_name="phase-demo")
        context = from_root(tmp_git_repo, run_id="run-1")
        context.assert_root_invariant()
        assert context.project_id == "fixture-project"
        assert context.worktree_id == "phase-demo"
        assert context.planning_authority == "issue-store:github-issues"
        assert context.run_id == "run-1"
        assert context.repo_slug == "acme/demo"
        assert context.remote.endswith("acme/demo.git")
        assert context.policy_overrides == (
            ("orchestration.planPolicy", "proposed"),
        )

    def test_envelope_round_trip_preserves_fields(self, tmp_git_repo: Path) -> None:
        _seed_repo(tmp_git_repo)
        original = from_root(tmp_git_repo, run_id="run-42")
        restored = from_envelope(original.to_envelope())
        assert restored == original


class TestManyConcurrentContexts:
    def test_contexts_do_not_alias(self, tmp_path: Path) -> None:
        def _init_repo(path: Path, index: int) -> Path:
            path.mkdir()
            git_base = ["git", "-C", str(path), "-c", "user.email=test@test", "-c", "user.name=Shipwright Test"]
            subprocess.run([*git_base, "init", "-b", "main"], check=True, capture_output=True)
            (path / "README.md").write_text("fixture\n", encoding="utf-8")
            subprocess.run([*git_base, "add", "README.md"], check=True, capture_output=True)
            subprocess.run([*git_base, "commit", "-m", "init"], check=True, capture_output=True)
            subprocess.run(
                [*git_base, "remote", "add", "origin", f"https://github.com/acme/repo-{index}.git"],
                check=True,
                capture_output=True,
            )
            _write_workflow_config(path, project=f"project-{index}")
            return path

        repos = [_init_repo(tmp_path / f"repo-{index}", index) for index in range(3)]

        def _build(path: Path) -> RepositoryContext:
            return from_root(path, run_id=f"run-{path.name}")

        with ThreadPoolExecutor(max_workers=3) as pool:
            contexts = list(pool.map(_build, repos))

        slugs = {context.repo_slug for context in contexts}
        assert slugs == {"acme/repo-0", "acme/repo-1", "acme/repo-2"}
        roots = {context.root for context in contexts}
        assert len(roots) == 3


class TestMidRunDirectoryChange:
    def test_root_invariant_fires_on_directory_change(self, tmp_git_repo: Path) -> None:
        _seed_repo(tmp_git_repo)
        context = from_root(tmp_git_repo)
        moved = tmp_git_repo.parent / "moved-repo"
        tmp_git_repo.rename(moved)
        object.__setattr__(context, "root", str(moved))
        with pytest.raises(RootInvariantError, match="invariant violated"):
            context.assert_root_invariant()

    def test_secret_envelope_key_is_rejected(self) -> None:
        payload = {
            "version": 1,
            "root": "/tmp/repo",
            "projectId": "demo",
            "worktreeId": "wt",
            "planningAuthority": "issue-store:github-issues",
            "credentialRefs": [],
            "memoryNamespace": "demo",
            "policyOverrides": {},
            "runId": None,
            "remote": "https://github.com/acme/demo.git",
            "repoSlug": "acme/demo",
            "destinationEndpoint": "https://api.github.com/user",
            "GITHUB_TOKEN": "secret",
        }
        with pytest.raises(RepositoryContextError, match="secret-bearing"):
            from_envelope(payload)

    def test_parse_envelope_from_env_helper(self, tmp_git_repo: Path) -> None:
        _seed_repo(tmp_git_repo)
        context = from_root(tmp_git_repo)
        raw = context.serialize_envelope()
        restored = parse_envelope(raw)
        assert restored.root == context.root
        assert CONTEXT_ENVELOPE_ENV not in os.environ
