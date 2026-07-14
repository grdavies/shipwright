"""PRD 068 phase 3 (R5) — merge run-next timeout and recovery."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.git]


def _load_wave_merge(repo_root: Path):
    path = repo_root / "scripts" / "wave_merge.py"
    spec = importlib.util.spec_from_file_location("wave_merge_r5", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(repo_root / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def test_merge_run_next_timeout_seconds_default(tmp_path: Path, repo_root: Path) -> None:
    wm = _load_wave_merge(repo_root)
    (tmp_path / ".cursor").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"version": 1, "deliver": {}}), encoding="utf-8"
    )
    assert wm.merge_run_next_timeout_seconds(tmp_path) == wm.DEFAULT_MERGE_RUN_NEXT_TIMEOUT_SECONDS
    (tmp_path / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"version": 1, "deliver": {"watchdog": {"mergeRunNextTimeoutSeconds": 42}}}),
        encoding="utf-8",
    )
    assert wm.merge_run_next_timeout_seconds(tmp_path) == 42


def test_preserve_merge_queue_from_journal_reenqueues_head() -> None:
    wm = _load_wave_merge(Path.cwd())
    state = {
        "mergeJournal": {"phase": "alpha", "head": "abc123", "key": "alpha"},
        "mergeQueue": [{"phaseSlug": "beta"}],
    }
    wm.preserve_merge_queue_from_journal(state)
    assert state["mergeJournal"] is None
    assert state["mergeQueue"][0]["phaseSlug"] == "alpha"
    assert state["mergeQueue"][0]["recoveredFromJournal"] is True
    assert state["mergeQueue"][1]["phaseSlug"] == "beta"


def test_timeout_after_journal_clears_without_manual_delete(
    tmp_git_repo: Path, repo_root: Path
) -> None:
    """Timeout after journal write recovers via queue preserve — no manual journal delete (R5)."""
    wm = _load_wave_merge(repo_root)
    target = "feat/demo"
    phase_slug = "demo-phase"
    phase_branch = "feat/demo-phase-alpha"
    subprocess.run(["git", "checkout", "-b", target], cwd=tmp_git_repo, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", phase_branch], cwd=tmp_git_repo, check=True, capture_output=True)
    subprocess.run(["git", "checkout", target], cwd=tmp_git_repo, check=True, capture_output=True)

    state = {
        "target": {"branch": target},
        "orchestratorWorktree": {"path": str(tmp_git_repo)},
        "mergeJournal": {"phase": phase_slug, "head": "deadbeef", "key": phase_slug},
        "mergeQueue": [],
        "phases": {"1": {"slug": phase_slug, "branch": phase_branch}},
    }
    state_path = tmp_git_repo / ".cursor" / "sw-deliver-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with patch.object(wm, "phase_already_merged", return_value=False):
        with pytest.raises(SystemExit):
            wm.handle_merge_run_next_timeout(
                tmp_git_repo,
                state,
                phase_slug=phase_slug,
                phase_branch=phase_branch,
                target=target,
                orch_wt=tmp_git_repo,
                timeout_seconds=1,
            )

    assert state["mergeJournal"] is None
    assert state["mergeQueue"][0]["phaseSlug"] == phase_slug
    assert state["mergeQueue"][0]["recoveredFromJournal"] is True


def test_merge_exec_journal_safety_clears_when_already_merged(
    tmp_git_repo: Path, repo_root: Path
) -> None:
    wm = _load_wave_merge(repo_root)
    target = "feat/demo"
    phase_slug = "demo-phase"
    phase_branch = "feat/demo-phase-alpha"
    subprocess.run(["git", "checkout", "-b", target], cwd=tmp_git_repo, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", phase_branch], cwd=tmp_git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "merge", "--no-ff", target, "-m", "align"],
        cwd=tmp_git_repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "checkout", target], cwd=tmp_git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "merge", "--no-ff", phase_branch, "-m", "land phase"],
        cwd=tmp_git_repo,
        check=True,
        capture_output=True,
    )

    state = {
        "mergeJournal": {"phase": phase_slug, "head": "abc", "key": phase_slug},
        "mergeQueue": [],
    }
    state_path = tmp_git_repo / ".cursor" / "sw-deliver-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state), encoding="utf-8")

    payload = wm.merge_exec_journal_safety(
        tmp_git_repo,
        state,
        phase_slug=phase_slug,
        phase_branch=phase_branch,
        target=target,
        wt=tmp_git_repo,
    )
    assert payload is not None
    assert payload.get("journalRecovered") is True
    assert state["mergeJournal"] is None


def test_merge_exec_refuses_journal_phase_mismatch(repo_root: Path) -> None:
    wm = _load_wave_merge(repo_root)
    state = {"mergeJournal": {"phase": "other", "head": "abc"}}
    with pytest.raises(SystemExit):
        wm.merge_exec_journal_safety(
            Path("/tmp/unused"),
            state,
            phase_slug="alpha",
            phase_branch="feat/alpha",
            target="feat/demo",
            wt=Path("/tmp/unused"),
        )
