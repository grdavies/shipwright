"""PRD 085 R1 — fail-closed plan adoption identity guard."""

from __future__ import annotations

import json
import sys
from pathlib import Path

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from wave_deliver_loop import compute_next_action, resolve_plan_with_adoption
from wave_run_paths import GLOBAL_PLAN_REL


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
