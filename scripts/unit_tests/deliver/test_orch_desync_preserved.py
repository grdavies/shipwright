"""PRD 276 R7 — adoption preserves true dual-drive / desync detection."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
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


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
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
    _git(primary, "branch", "feat/desync-demo")
    orch = primary / ".sw-worktrees" / "desync-demo-orchestrator"
    orch.parent.mkdir(parents=True, exist_ok=True)
    _git(primary, "worktree", "add", "-q", str(orch), "feat/desync-demo")
    state = {
        "runId": "deliver-desync-preserve",
        "verdict": "running",
        "source_task_list": "docs/prds/276-demo/tasks-276-demo.md",
        "target": {"branch": "feat/desync-demo", "slug": "desync-demo"},
        "phases": {"1": {"status": "pending", "slug": "phase-one"}},
        "orchestratorWorktree": {
            "path": str(orch),
            "branch": "feat/desync-demo",
            "name": "desync-demo-orchestrator",
        },
    }
    plan = {"target": state["target"], "source_task_list": state["source_task_list"]}
    return primary, orch, state, plan


def test_adopt_preserves_true_dual_drive_desync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """R7 — fresh peer heartbeat blocks adopt; canonical desync still detected after adopt."""
    primary, orch, state, plan = _repo_with_orch(tmp_path)
    monkeypatch.chdir(primary)
    monkeypatch.delenv(ORCH_CWD_ADOPTED_ENV, raising=False)

    # Fresh heartbeat → dual-drive: adopt must fail closed (not mask contention).
    state["driverHeartbeatAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with pytest.raises(SystemExit) as exc:
        try_adopt_recorded_orchestrator_worktree(primary, state, plan, loop_args=[])
    assert exc.value.code == 20
    payload = json.loads(capsys.readouterr().out)
    assert payload["cause"] == "adopt:dual-drive-preserved"
    assert payload["halt"] == "double-drive"
    assert payload.get("resumeCommand", "").startswith("/sw-deliver run")
    assert Path.cwd().resolve() == primary.resolve()

    # After a successful adopt (self-wake), true canonical desync still surfaces.
    state.pop("driverHeartbeatAt", None)
    monkeypatch.delenv(ORCH_CWD_ADOPTED_ENV, raising=False)
    with patch("wave_lifecycle.adopt_orchestrator_worktree"):
        result = try_adopt_recorded_orchestrator_worktree(
            primary, state, plan, loop_args=["--self-wake"], perform_reentry=True
        )
    assert result["reentry"] is True
    assert Path.cwd().resolve() == orch.resolve()

    def _boom(*_a, **_k):
        raise SystemExit("canonical desync")

    with patch("wave_deliver_loop.sync_canonical_state_read", side_effect=_boom):
        cause = check_deliver_hang_desync(orch, state)
    assert cause == "deliver:canonical-state-desync"
