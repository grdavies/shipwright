"""PRD 068 phase 1 — resume short-circuit and orchestrator adopt (R1–R2)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=tmp_path, check=True)
    scripts = tmp_path / "scripts"
    if not scripts.exists():
        scripts.symlink_to(Path(__file__).resolve().parents[2], target_is_directory=True)
    return tmp_path


def _write_task_list(repo: Path, slug: str = "demo") -> str:
    rel = f"docs/prds/068-{slug}/tasks-068-{slug}.md"
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
type: tasks
frozen: true
topic: {slug}
---

### 1. Alpha

- [ ] 1.1 Do thing
""",
        encoding="utf-8",
    )
    return rel


def _running_state(task_list: str, slug: str = "demo") -> dict:
    return {
        "verdict": "running",
        "target": {"type": "feat", "slug": slug, "branch": f"feat/{slug}"},
        "source_task_list": task_list,
        "currentWave": 1,
        "nextAction": "dispatch-ship",
        "phases": {
            "1": {"id": "1", "slug": "alpha", "status": "pending"},
        },
    }


def test_deliver_state_consumable_pass(git_repo: Path) -> None:
    from wave_deliver import deliver_state_consumable

    task_list = _write_task_list(git_repo)
    state = _running_state(task_list)
    check = deliver_state_consumable(
        git_repo, state, task_list=task_list, unit_id="demo"
    )
    assert check["consumable"] is True
    assert check["target"] == "feat/demo"


def test_deliver_state_consumable_wrong_slug(git_repo: Path) -> None:
    from wave_deliver import deliver_state_consumable

    task_list = _write_task_list(git_repo)
    state = _running_state(task_list)
    check = deliver_state_consumable(
        git_repo, state, task_list=task_list, unit_id="other-slug"
    )
    assert check["consumable"] is False
    assert check.get("halt") is True
    assert check.get("cause") == "resume:wrong-slug"


def test_deliver_state_consumable_terminal(git_repo: Path) -> None:
    from wave_deliver import deliver_state_consumable

    task_list = _write_task_list(git_repo)
    state = _running_state(task_list)
    state["verdict"] = "complete"
    check = deliver_state_consumable(git_repo, state, task_list=task_list)
    assert check["consumable"] is False
    assert check.get("reason") == "terminal-verdict"


def test_deliver_state_consumable_foreign_task_list(git_repo: Path) -> None:
    from wave_deliver import deliver_state_consumable

    task_list = _write_task_list(git_repo)
    state = _running_state("docs/prds/other/tasks.md")
    check = deliver_state_consumable(git_repo, state, task_list=task_list)
    assert check["consumable"] is False
    assert check.get("cause") == "resume:foreign-state"


def test_preflight_resume_skips_base_probe(git_repo: Path) -> None:
    from wave_deliver import cmd_preflight

    task_list = _write_task_list(git_repo)
    state = _running_state(task_list)
    scoped = git_repo / ".cursor" / "sw-deliver-state.demo.json"
    scoped.parent.mkdir(parents=True, exist_ok=True)
    scoped.write_text(json.dumps(state), encoding="utf-8")

    with patch("wave_deliver.run_base_preflight") as base_pf:
        with pytest.raises(SystemExit) as exc:
            cmd_preflight(
                git_repo,
                ["preflight", "--task-list", task_list, "--skip-base-check"],
            )
        assert exc.value.code == 0
        base_pf.assert_not_called()


def test_truncated_state_halts(git_repo: Path) -> None:
    from wave_deliver import evaluate_resume_short_circuit

    task_list = _write_task_list(git_repo)
    scoped = git_repo / ".cursor" / "sw-deliver-state.demo.json"
    scoped.parent.mkdir(parents=True, exist_ok=True)
    scoped.write_text('{"verdict": "running", "phases": {', encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        evaluate_resume_short_circuit(git_repo, ["--task-list", task_list])
    assert exc.value.code == 20


def test_orchestrator_adopt_basename_refused(git_repo: Path) -> None:
    from wave_deliver_loop import try_adopt_recorded_orchestrator_worktree

    state = {
        "target": {"branch": "feat/demo"},
        "orchestratorWorktree": {"path": "demo-orchestrator", "branch": "feat/demo"},
    }
    with pytest.raises(SystemExit) as exc:
        try_adopt_recorded_orchestrator_worktree(git_repo, state, {})
    assert exc.value.code == 20


def test_orchestrator_adopt_branch_mismatch(git_repo: Path) -> None:
    from wave_deliver_loop import try_adopt_recorded_orchestrator_worktree

    wt = git_repo / ".sw-worktrees" / "demo-orchestrator"
    wt.mkdir(parents=True)
    state = {
        "target": {"branch": "feat/demo"},
        "orchestratorWorktree": {
            "path": str(wt),
            "branch": "feat/other",
            "name": "demo-orchestrator",
        },
    }
    with pytest.raises(SystemExit) as exc:
        try_adopt_recorded_orchestrator_worktree(git_repo, state, {})
    assert exc.value.code == 20
