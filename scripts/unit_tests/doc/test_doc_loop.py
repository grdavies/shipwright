"""PRD 085 R7/R8 — doc-loop run-id validation and canonical anchoring."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from doc_loop import doc_run_directory, doc_runs_root, mint_doc_run_id
from wave_lock import doc_run_locks_dir
from wave_run_paths import RunIdRequiredError, require_run_id


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    return root


@pytest.mark.parametrize(
    "unsafe",
    [
        "../../unexpected-directory",
        "../sibling",
        "foo/bar",
        "",
        " ",
        "/absolute",
    ],
)
def test_run_id_resolution_rejects_unsafe_values(repo: Path, unsafe: str) -> None:
    with pytest.raises(RunIdRequiredError):
        require_run_id(unsafe)
    with pytest.raises(RunIdRequiredError):
        doc_run_directory(repo, unsafe)


def test_run_id_resolution_accepts_minted_shape(repo: Path) -> None:
    run_id = mint_doc_run_id(repo)
    assert require_run_id(run_id) == run_id
    assert doc_run_directory(repo, run_id) == doc_runs_root(repo) / run_id


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = "Test"
    env["GIT_COMMITTER_NAME"] = "Test"
    # Git accepts identifier-only emails for fixture repos; avoid @ literals in source (secret-scan).
    env["GIT_AUTHOR_EMAIL"] = "nobody"
    env["GIT_COMMITTER_EMAIL"] = "nobody"
    return env


def test_doc_runs_root_matches_lock_anchor_from_linked_worktree(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    env = _git_env()
    subprocess.run(["git", "init", "-q"], cwd=primary, check=True, capture_output=True, env=env)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-q", "-m", "init"],
        cwd=primary,
        check=True,
        capture_output=True,
        env=env,
    )
    (primary / ".cursor").mkdir(parents=True, exist_ok=True)

    worktree = tmp_path / "docs-wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "docs/topic", str(worktree)],
        cwd=primary,
        check=True,
        capture_output=True,
        env=env,
    )
    (worktree / ".cursor").mkdir(parents=True, exist_ok=True)

    runs_from_worktree = doc_runs_root(worktree)
    locks_from_worktree = doc_run_locks_dir(worktree)
    expected_runs = (primary / ".cursor" / "sw-doc-runs").resolve()
    expected_locks = (primary / ".cursor" / "sw-doc-run-locks").resolve()

    assert runs_from_worktree == expected_runs
    assert locks_from_worktree == expected_locks
    assert runs_from_worktree.parent == locks_from_worktree.parent
    assert not (worktree / ".cursor" / "sw-doc-runs").exists()
