"""PRD 085 R1 — fail-closed plan adoption identity guard."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from wave_deliver_loop import (
    compute_next_action,
    phase_run_dir_for_slug,
    resolve_plan_with_adoption,
    trunk_base_persisted,
)
from wave_run_paths import GLOBAL_PLAN_REL, global_plan_path, plan_path, runs_root, state_path
from wave_state import path_normalize_anchor, save_run_scoped_state, scoped_paths


def _phase_plan(task_list: str, *, slug: str = "alpha") -> dict:
    return {
        "mode": "phase",
        "source_task_list": task_list,
        "target": {"type": "feat", "slug": slug, "branch": f"feat/{slug}"},
        "items": [{"id": "1", "slug": "phase-a", "branch": f"feat/{slug}-phase-phase-a"}],
        "waves": [["1"]],
        "edges": [],
    }


def test_stale_global_plan_refused_for_different_task_list(tmp_path: Path) -> None:
    task_a = "docs/prds/a/tasks-a.md"
    task_b = "docs/prds/b/tasks-b.md"
    (tmp_path / "docs/prds/a").mkdir(parents=True)
    (tmp_path / "docs/prds/b").mkdir(parents=True)
    (tmp_path / task_a).write_text("# tasks\n", encoding="utf-8")
    (tmp_path / task_b).write_text("# tasks\n", encoding="utf-8")

    stale = _phase_plan(task_a, slug="stale-target")
    transient = tmp_path / GLOBAL_PLAN_REL
    transient.parent.mkdir(parents=True, exist_ok=True)
    transient.write_text(json.dumps(stale), encoding="utf-8")

    state: dict = {"verdict": "running"}
    plan, state = resolve_plan_with_adoption(tmp_path, state, task_b)
    assert plan == {}

    state["source_task_list"] = task_b
    step = compute_next_action(tmp_path, state, plan)
    assert step["action"] == "plan"


def test_stale_global_plan_does_not_route_to_lock_acquire(tmp_path: Path) -> None:
    task_a = "docs/prds/a/tasks-a.md"
    task_b = "docs/prds/b/tasks-b.md"
    (tmp_path / "docs/prds/a").mkdir(parents=True)
    (tmp_path / "docs/prds/b").mkdir(parents=True)
    (tmp_path / task_a).write_text("# tasks\n", encoding="utf-8")
    (tmp_path / task_b).write_text("# tasks\n", encoding="utf-8")

    stale = _phase_plan(task_a, slug="stale-branch")
    transient = tmp_path / GLOBAL_PLAN_REL
    transient.parent.mkdir(parents=True, exist_ok=True)
    transient.write_text(json.dumps(stale), encoding="utf-8")

    state: dict = {"verdict": "running", "source_task_list": task_b}
    plan, _ = resolve_plan_with_adoption(tmp_path, state, task_b)
    assert plan == {}
    step = compute_next_action(tmp_path, state, plan)
    assert step["action"] == "plan"
    assert step["action"] != "lock-acquire"


def test_matching_transient_plan_still_adopted_before_state_init(tmp_path: Path) -> None:
    task_list = "docs/prds/demo/tasks-demo.md"
    (tmp_path / "docs/prds/demo").mkdir(parents=True)
    (tmp_path / task_list).write_text("# tasks\n", encoding="utf-8")

    plan_doc = _phase_plan(task_list)
    transient = tmp_path / GLOBAL_PLAN_REL
    transient.parent.mkdir(parents=True, exist_ok=True)
    transient.write_text(json.dumps(plan_doc), encoding="utf-8")

    state: dict = {"verdict": "running"}
    plan, _ = resolve_plan_with_adoption(tmp_path, state, task_list)
    assert plan.get("mode") == "phase"
    step = compute_next_action(tmp_path, state, plan)
    assert step["action"] == "lock-acquire"
    assert step.get("target") == "feat/alpha"


def test_orchestrator_worktree_cwd_anchors_deliver_paths_to_primary(tmp_path: Path) -> None:
    """R4 — deliver loop from orchestrator cwd without local .cursor mirror."""
    primary = tmp_path / "primary"
    primary.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=primary, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=primary, check=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=primary, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "init"], cwd=primary, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=primary, check=True)

    orch = tmp_path / "orch"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "feat/demo-orch", str(orch)],
        cwd=primary,
        check=True,
    )
    assert not (orch / ".cursor").exists()

    anchor = path_normalize_anchor(orch)
    assert anchor == path_normalize_anchor(primary)

    cursor = anchor / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    (cursor / "sw-base-state.json").write_text(
        json.dumps({"trunkBase": {"name": "main", "sha": "abc123"}}),
        encoding="utf-8",
    )

    plan_doc = {"mode": "phase", "source_task_list": "tasks.md"}
    global_plan_path(primary).parent.mkdir(parents=True, exist_ok=True)
    global_plan_path(primary).write_text(json.dumps(plan_doc), encoding="utf-8")

    run_id = "deliver-orch-anchor-test"
    slug = "demo-phase"
    run_state = {"verdict": "running", "runId": run_id}
    save_run_scoped_state(primary, run_id, run_state)

    assert trunk_base_persisted(orch) is True
    assert global_plan_path(orch) == global_plan_path(primary)
    assert runs_root(orch) == runs_root(primary)
    assert state_path(orch, run_id).is_file()
    assert phase_run_dir_for_slug(orch, slug) == phase_run_dir_for_slug(primary, slug)

    for artifact in (
        global_plan_path(orch),
        state_path(orch, run_id),
        plan_path(orch, run_id),
        phase_run_dir_for_slug(orch, slug),
        scoped_paths(orch, "feat/demo-orch")["state"],
    ):
        rel = artifact.resolve().relative_to(anchor.resolve())
        assert not str(rel).startswith("..")

    new_state = {"verdict": "running", "runId": run_id, "note": "orch-write"}
    save_run_scoped_state(orch, run_id, new_state)
    assert json.loads(state_path(primary, run_id).read_text(encoding="utf-8"))["note"] == "orch-write"
