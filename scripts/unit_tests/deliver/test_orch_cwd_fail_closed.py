"""PRD 276 R6 — missing/invalid orch path fails closed with typed resumeCommand."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_deliver_loop import try_adopt_recorded_orchestrator_worktree


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )


def _init_primary(tmp_path: Path) -> Path:
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "init", "-q")
    _git(primary, "config", "user.email", "t@t.com")
    _git(primary, "config", "user.name", "Test")
    _git(primary, "commit", "--allow-empty", "-qm", "init")
    return primary


def _capture_fail(capsys: pytest.CaptureFixture[str], fn) -> dict:
    with pytest.raises(SystemExit) as exc:
        fn()
    assert exc.value.code == 20
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload.get("verdict") == "fail"
    return payload


def test_invalid_orch_path_fail_closed_with_resume(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R6 — missing orch path → typed cause + resumeCommand."""
    primary = _init_primary(tmp_path)
    missing = primary / ".sw-worktrees" / "missing-orchestrator"
    state = {
        "runId": "deliver-orch-fail-closed",
        "verdict": "running",
        "source_task_list": "docs/prds/276-demo/tasks-276-demo.md",
        "target": {"branch": "feat/orch-fail", "slug": "orch-fail"},
        "phases": {"1": {"status": "pending"}},
        "orchestratorWorktree": {
            "path": str(missing),
            "branch": "feat/orch-fail",
            "name": "orch-fail-orchestrator",
        },
    }
    plan = {"target": state["target"], "source_task_list": state["source_task_list"]}

    payload = _capture_fail(
        capsys,
        lambda: try_adopt_recorded_orchestrator_worktree(primary, state, plan),
    )
    assert payload["halt"] == "orchestrator-adopt"
    assert payload["cause"] == "resume:orchestrator-path-missing"
    assert isinstance(payload.get("resumeCommand"), str)
    assert payload["resumeCommand"].startswith("/sw-deliver run")
    assert "docs/prds/276-demo/tasks-276-demo.md" in payload["resumeCommand"]


def test_basename_only_orch_path_fail_closed_with_resume(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R6 — basename-only recorded path refuses invent with resumeCommand."""
    primary = _init_primary(tmp_path)
    state = {
        "runId": "deliver-orch-basename",
        "verdict": "running",
        "source_task_list": "docs/prds/276-demo/tasks-276-demo.md",
        "target": {"branch": "feat/orch-fail", "slug": "orch-fail"},
        "phases": {"1": {"status": "pending"}},
        "orchestratorWorktree": {"path": "orphan-basename-only"},
    }
    plan = {"target": state["target"], "source_task_list": state["source_task_list"]}

    payload = _capture_fail(
        capsys,
        lambda: try_adopt_recorded_orchestrator_worktree(primary, state, plan),
    )
    assert payload["cause"] == "resume:orchestrator-basename-only"
    assert payload.get("resumeCommand", "").startswith("/sw-deliver run")
