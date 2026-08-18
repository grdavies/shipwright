"""PRD 276 R5/R8 — repo-root invocation succeeds via validated orch cwd adopt."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_deliver_loop import (
    ORCH_CWD_ADOPTED_ENV,
    check_deliver_hang_desync,
    try_adopt_recorded_orchestrator_worktree,
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )


def _repo_with_orch(tmp_path: Path) -> tuple[Path, Path, dict, dict]:
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "init", "-q")
    _git(primary, "config", "user.email", "t@t.com")
    _git(primary, "config", "user.name", "Test")
    _git(primary, "commit", "--allow-empty", "-qm", "init")
    _git(primary, "branch", "-M", "main")
    _git(primary, "branch", "feat/orch-adopt-demo")
    orch = primary / ".sw-worktrees" / "orch-adopt-demo-orchestrator"
    orch.parent.mkdir(parents=True, exist_ok=True)
    _git(primary, "worktree", "add", "-q", str(orch), "feat/orch-adopt-demo")
    state = {
        "runId": "deliver-orch-adopt-happy",
        "verdict": "running",
        "source_task_list": "docs/prds/276-demo/tasks-276-demo.md",
        "target": {"branch": "feat/orch-adopt-demo", "slug": "orch-adopt-demo"},
        "phases": {"1": {"status": "pending", "slug": "phase-one"}},
        "orchestratorWorktree": {
            "path": str(orch),
            "branch": "feat/orch-adopt-demo",
            "name": "orch-adopt-demo-orchestrator",
        },
    }
    plan = {
        "source_task_list": state["source_task_list"],
        "target": state["target"],
    }
    return primary, orch, state, plan


def test_repo_root_invocation_succeeds_via_adopt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R8 — repo-root invocation adopts orch WT without manual cd."""
    primary, orch, state, plan = _repo_with_orch(tmp_path)
    monkeypatch.chdir(primary)
    monkeypatch.delenv(ORCH_CWD_ADOPTED_ENV, raising=False)

    with patch("wave_lifecycle.adopt_orchestrator_worktree"):
        result = try_adopt_recorded_orchestrator_worktree(
            primary, state, plan, loop_args=["--self-wake"], perform_reentry=True
        )

    assert result["adopted"] is True
    assert result["reentry"] is True
    assert Path(result["cwd"]).resolve() == orch.resolve()
    assert Path(result["delegateRoot"]).resolve() == orch.resolve()
    assert Path.cwd().resolve() == orch.resolve()
    # Recoverable skew is gone after adopt — no manual cd required.
    assert check_deliver_hang_desync(orch, state) != "deliver:orchestrator-cwd-skew"


def test_deliver_adopts_valid_orch_worktree_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R5 — valid recorded orch path is adopted without manual cd."""
    primary, orch, state, plan = _repo_with_orch(tmp_path)
    monkeypatch.chdir(primary)
    monkeypatch.delenv(ORCH_CWD_ADOPTED_ENV, raising=False)

    with patch("wave_lifecycle.adopt_orchestrator_worktree"):
        result = try_adopt_recorded_orchestrator_worktree(
            primary, state, plan, loop_args=["--self-wake"], perform_reentry=True
        )

    assert result.get("path") == str(orch.resolve()) or Path(result["path"]).resolve() == orch.resolve()
    assert result["reentry"] is True
    assert "identity" in result
    assert result["identity"]["worktreeRegistered"] is True
    assert result["identity"]["branch"] == "feat/orch-adopt-demo"


def test_adopt_is_validated_reentry_not_path_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R13 — path-record alone is insufficient; cwd must be set via re-entry."""
    primary, orch, state, plan = _repo_with_orch(tmp_path)
    monkeypatch.chdir(primary)
    monkeypatch.delenv(ORCH_CWD_ADOPTED_ENV, raising=False)

    with patch("wave_lifecycle.adopt_orchestrator_worktree"):
        path_only = try_adopt_recorded_orchestrator_worktree(
            primary, state, plan, loop_args=["--self-wake"], perform_reentry=False
        )
    assert path_only.get("insufficientWithoutReentry") is True
    assert path_only.get("reentry") is False
    # Still at primary — skew remains if we only recorded the path.
    assert Path.cwd().resolve() == primary.resolve()
    assert check_deliver_hang_desync(primary, state) == "deliver:orchestrator-cwd-skew"

    monkeypatch.delenv(ORCH_CWD_ADOPTED_ENV, raising=False)
    with patch("wave_lifecycle.adopt_orchestrator_worktree"):
        rebound = try_adopt_recorded_orchestrator_worktree(
            primary, state, plan, loop_args=["--self-wake"], perform_reentry=True
        )
    assert rebound["reentry"] is True
    assert Path(rebound["cwd"]).resolve() == orch.resolve()
    assert Path.cwd().resolve() == orch.resolve()
