"""PRD 089 R6 — verified commit outcome for feature-seed completion."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from wave_spec_seed import (
    ambiguous_remote_state_default,
    build_incomplete_completion,
    build_verified_completion,
    completion_from_seed_payload,
)
from wave_spec_seed_guard import assert_handoff_completion_remote_state


def subprocess_head(repo: Path, branch: str) -> str:
    out = subprocess.run(
        ["git", "rev-parse", branch],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
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
    subprocess.run(["git", "branch", "-M", "main"], cwd=root, check=True, capture_output=True)
    return root


def test_ambiguous_dry_run_default_rejected_as_completion() -> None:
    remote_state = ambiguous_remote_state_default("feat/demo")
    with pytest.raises(PermissionError, match="ambiguous unflipped dryRun default"):
        assert_handoff_completion_remote_state(remote_state)


def test_unset_dry_run_without_commit_rejected() -> None:
    with pytest.raises(PermissionError, match="ambiguous remote state"):
        assert_handoff_completion_remote_state({"branch": "feat/demo", "commit": None})


def test_verified_completion_remote_state_accepted(repo: Path) -> None:
    head = subprocess_head(repo, "main")
    completion = build_verified_completion(repo, "main", head, "committed")
    assert completion["complete"] is True
    remote_state = {
        "branch": "main",
        "commit": head,
        "dryRun": False,
        "completion": completion,
    }
    assert_handoff_completion_remote_state(remote_state)


def test_incomplete_completion_outcome_rejected() -> None:
    completion = build_incomplete_completion("feat/demo", reason="dry-run", dry_run=True)
    remote_state = {
        "branch": "feat/demo",
        "commit": None,
        "dryRun": True,
        "completion": completion,
    }
    with pytest.raises(PermissionError):
        assert_handoff_completion_remote_state(remote_state)


def test_completion_from_seed_payload_dry_run_incomplete(repo: Path) -> None:
    completion = completion_from_seed_payload(
        repo,
        {"verdict": "pass", "dry_run": True, "branch": "feat/demo"},
    )
    assert completion["complete"] is False
    assert completion.get("dryRun") is True


def test_already_present_without_commit_sha_in_payload_resolves_head(repo: Path) -> None:
    head = subprocess_head(repo, "main")
    completion = completion_from_seed_payload(
        repo,
        {"verdict": "pass", "skipped": True, "branch": "main"},
    )
    assert completion["outcome"] == "already-present"
    assert completion["verified"] is True
    assert completion["commit"] == head
    assert completion["complete"] is True
