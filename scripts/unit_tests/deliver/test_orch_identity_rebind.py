"""PRD 276 R14 — execution-time identity rebind closes TOCTOU replacement window."""

from __future__ import annotations

import json
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
    rebind_orch_execution_identity,
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


def _repo_with_orch(tmp_path: Path) -> tuple[Path, Path, dict, dict, str]:
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "init", "-q")
    _git(primary, "config", "user.email", "t@t.com")
    _git(primary, "config", "user.name", "Test")
    _git(primary, "commit", "--allow-empty", "-qm", "init")
    _git(primary, "branch", "-M", "main")
    _git(primary, "branch", "feat/rebind-demo")
    orch = primary / ".sw-worktrees" / "rebind-demo-orchestrator"
    orch.parent.mkdir(parents=True, exist_ok=True)
    _git(primary, "worktree", "add", "-q", str(orch), "feat/rebind-demo")
    head = _git(orch, "rev-parse", "HEAD").stdout.strip()
    state = {
        "runId": "deliver-identity-rebind",
        "verdict": "running",
        "source_task_list": "docs/prds/276-demo/tasks-276-demo.md",
        "target": {"branch": "feat/rebind-demo", "slug": "rebind-demo"},
        "phases": {"1": {"status": "pending"}},
        "orchestratorWorktree": {
            "path": str(orch),
            "branch": "feat/rebind-demo",
            "name": "rebind-demo-orchestrator",
        },
    }
    plan = {"target": state["target"], "source_task_list": state["source_task_list"]}
    return primary, orch, state, plan, head


def test_execution_time_identity_rebind_closes_toctou(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """R14 — rebind git-common-dir, worktree registration, branch HEAD, run identity."""
    primary, orch, state, plan, head = _repo_with_orch(tmp_path)
    monkeypatch.chdir(primary)
    monkeypatch.delenv(ORCH_CWD_ADOPTED_ENV, raising=False)

    identity = rebind_orch_execution_identity(
        primary, orch, state, plan, target="feat/rebind-demo"
    )
    assert identity["worktreeRegistered"] is True
    assert identity["branch"] == "feat/rebind-demo"
    assert identity["head"] == head
    assert identity["runId"] == "deliver-identity-rebind"
    assert identity["source_task_list"] == state["source_task_list"]
    assert identity["gitCommonDir"]
    assert "reboundAt" in identity

    with patch("wave_lifecycle.adopt_orchestrator_worktree"):
        result = try_adopt_recorded_orchestrator_worktree(
            primary, state, plan, loop_args=["--self-wake"], perform_reentry=True
        )
    assert result["identity"]["head"] == head
    assert result["identity"]["worktreeRegistered"] is True

    # TOCTOU: directory that looks like orch but is not a registered worktree → fail closed.
    impostor = primary / ".sw-worktrees" / "rebind-demo-orchestrator-impostor"
    impostor.mkdir(parents=True, exist_ok=True)
    # Plain directory (no git) under managed roots — registration check fails.
    with pytest.raises(SystemExit) as exc:
        rebind_orch_execution_identity(
            primary, impostor, state, plan, target="feat/rebind-demo"
        )
    assert exc.value.code == 20
    payload = json.loads(capsys.readouterr().out)
    assert payload["cause"] in {
        "adopt:worktree-unregistered",
        "adopt:git-common-dir-unresolved",
        "adopt:git-common-dir-mismatch",
    }
    assert payload.get("resumeCommand", "").startswith("/sw-deliver run")
