"""PRD 085 R2 — atomic pending-to-final plan persistence."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path

import pytest

from wave_run_paths import plan_path, plan_pending_path
from wave_run_plan import ensure_run_id, load_verified_plan, persist_plan


def _sample_plan(*, branch: str = "feat/demo", slug: str = "demo", task_list: str) -> dict:
    return {
        "mode": "phase",
        "source_task_list": task_list,
        "target": {"type": "feat", "slug": slug, "branch": branch},
        "items": [{"id": "1", "slug": "alpha"}],
        "waves": [["1"]],
        "edges": [],
    }


def _init_git(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    (path / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def test_persist_plan_uses_pending_then_final_path(tmp_path: Path) -> None:
    _init_git(tmp_path)
    state: dict = {}
    run_id = ensure_run_id(tmp_path, state)
    plan = _sample_plan(task_list="docs/tasks-a.md")
    persist_plan(tmp_path, run_id, plan, state)

    final = plan_path(tmp_path, run_id)
    pending = plan_pending_path(tmp_path, run_id)
    assert final.is_file()
    assert not pending.is_file()
    loaded = json.loads(final.read_text(encoding="utf-8"))
    assert loaded["target"]["branch"] == "feat/demo"
    assert state.get("planHash")


def test_interleaved_plan_actions_keep_isolated_run_directories(tmp_path: Path) -> None:
    _init_git(tmp_path)
    task_a = "docs/prds/a/tasks-a.md"
    task_b = "docs/prds/b/tasks-b.md"
    plan_a = _sample_plan(branch="feat/alpha", slug="alpha", task_list=task_a)
    plan_b = _sample_plan(branch="feat/beta", slug="beta", task_list=task_b)

    state_a: dict = {}
    state_b: dict = {}
    run_a = ensure_run_id(tmp_path, state_a)
    run_b = ensure_run_id(tmp_path, state_b)
    barrier = threading.Barrier(2)

    def persist_a() -> None:
        pending = plan_pending_path(tmp_path, run_a)
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text(json.dumps(plan_a), encoding="utf-8")
        barrier.wait()
        persist_plan(tmp_path, run_a, plan_a, state_a)

    def persist_b() -> None:
        pending = plan_pending_path(tmp_path, run_b)
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text(json.dumps(plan_b), encoding="utf-8")
        barrier.wait()
        persist_plan(tmp_path, run_b, plan_b, state_b)

    t_a = threading.Thread(target=persist_a)
    t_b = threading.Thread(target=persist_b)
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    loaded_a = load_verified_plan(tmp_path, run_a, state_a)
    loaded_b = load_verified_plan(tmp_path, run_b, state_b)
    assert loaded_a["target"]["branch"] == "feat/alpha"
    assert loaded_b["target"]["branch"] == "feat/beta"
    assert loaded_a["source_task_list"] == task_a
    assert loaded_b["source_task_list"] == task_b


def test_invalid_plan_rejected_before_final_write(tmp_path: Path) -> None:
    _init_git(tmp_path)
    state: dict = {}
    run_id = ensure_run_id(tmp_path, state)
    with pytest.raises(Exception):
        persist_plan(tmp_path, run_id, {"mode": "phase"}, state)
    assert not plan_path(tmp_path, run_id).is_file()
