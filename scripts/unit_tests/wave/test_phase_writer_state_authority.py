"""Phase-local stale snapshots must never become primary conductor state."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import wave_state as state
from wave_phase_pr import persist_open_pr_number


@pytest.fixture
def linked_state(tmp_path):
    primary = tmp_path / "primary"
    primary.mkdir()
    def git(*args):
        subprocess.run(["git", "-C", str(primary), *args], check=True, capture_output=True)
    git("init", "-q")
    git("-c", "user.name=Test", "-c", "user.email=test" + "@example.invalid", "commit", "--allow-empty", "-qm", "fixture")
    phase = primary / ".sw-worktrees/phase"
    orch = primary / ".sw-worktrees/orchestrator"
    git("worktree", "add", "--detach", str(phase), "HEAD")
    git("worktree", "add", "--detach", str(orch), "HEAD")
    current = {"runId": "fixture-run", "target": {"branch": "feat/fixture"},
               "orchestratorWorktree": {"path": str(orch)},
               "phases": {"1": {"slug": "baseline", "status": "blocked"}},
               "verdict": "blocked", "cause": "phase-timeout:1", "driverIterationCount": 14,
               "budgetCounters": {"executionIterationCount": 11}, "remediationAttempts": {"1": 2},
               "runStartedAt": "2026-09-20T22:58:43Z", "updatedAt": "2026-09-21T23:05:22Z"}
    stale = copy.deepcopy(current)
    stale.update(driverIterationCount=9, verdict="running", updatedAt="2026-09-21T18:54:42Z")
    stale.pop("budgetCounters")
    rel = Path(".cursor/sw-deliver-state.fixture.json")
    for root, data in ((primary, current), (orch, current), (phase, stale)):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(json.dumps(data))
    (primary / ".cursor/sw-deliver-state.json").write_text(json.dumps({"migrated": True, "scopedPath": str(rel), "target": "feat/fixture"}))
    return primary, phase, orch, rel, current, stale


@pytest.mark.parametrize("writer", ["pr", "execute"])
def test_phase_writers_preserve_primary_counters_and_update_orchestrator(linked_state, writer):
    primary, phase, orch, rel, current, stale = linked_state
    if writer == "pr":
        persist_open_pr_number(phase, phase_slug="baseline", number=351)
    else:
        task = phase / "tasks.md"
        task.write_text("---\nfrozen: true\n---\n- [ ] 1.1 Check\n")
        script = Path(state.__file__).with_name("execute_task_status.py")
        env = {**os.environ, "SW_TASK_LIST": str(task), "SW_PHASE_SLUG": "baseline"}
        proc = subprocess.run([sys.executable, str(script), "--task-ref", "1.1", "--write", '{"verdict":"pass"}'],cwd=phase,env=env,capture_output=True,text=True)
        assert proc.returncode == 0,proc.stdout+proc.stderr
    updated = json.loads((primary / rel).read_text())
    for key in ("verdict", "cause", "driverIterationCount", "budgetCounters", "remediationAttempts", "runStartedAt"):
        assert updated[key] == current[key]
    assert json.loads((orch / rel).read_text()) == updated
    assert json.loads((phase / rel).read_text()) == stale
    if writer == "pr":
        assert updated["phases"]["1"]["openPrNumber"] == 351
    else:
        assert updated["taskLedger"]["tasks"]["1.1"]["done"] is True


def test_run_breadcrumb_is_primary_anchored(linked_state):
    primary, phase, orch, rel, current, stale = linked_state
    run_rel = Path(".cursor/sw-deliver-runs/fixture-run/state.json")
    for root,data in ((primary,current),(phase,stale)):
        (root/run_rel).parent.mkdir(parents=True,exist_ok=True)
        (root/run_rel).write_text(json.dumps(data))
    breadcrumb={"migrated":True,"runId":"fixture-run","runScopedPath":str(run_rel)}
    assert state._run_scoped_path_from_breadcrumb(phase,breadcrumb)==primary/run_rel


def test_missing_primary_does_not_read_local_breadcrumb_target(linked_state):
    primary, phase, orch, rel, current, stale = linked_state
    (primary/rel).unlink()
    assert state._scoped_path_from_breadcrumb(phase,{"scopedPath":str(rel)}) is None
