"""PRD 081 R19 — duplicate same-target invocation blocked before mutation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from wave_lock import target_lock_path_for
from wave_run_paths import run_directory
from wave_target_lock import acquire_target_lock


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return root


@pytest.fixture(autouse=True)
def anchor_repo(repo: Path):
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=repo):
        yield


def test_second_target_invocation_blocked_before_run_directory(repo: Path) -> None:
    target = "feat/workflow-state-machine-hardening"
    first = acquire_target_lock(repo, target, "run-a")
    assert first["verdict"] == "pass"

    second = acquire_target_lock(repo, target, "run-b")
    assert second["verdict"] == "fail"
    assert second["error"] == "target-lock-held"

    assert not run_directory(repo, "run-b").exists()
    assert not run_directory(repo, "run-a").exists()

    lock_path = target_lock_path_for(repo, target)
    meta = json.loads(lock_path.read_text(encoding="utf-8"))
    assert meta["runId"] == "run-a"


def test_spec_seed_refused_without_target_lock(repo: Path) -> None:
    from wave_spec_seed_guard import assert_target_lock_for_seed

    with pytest.raises(PermissionError, match="target lock not held"):
        assert_target_lock_for_seed(repo, "feat/demo", "deliver-test-run")
