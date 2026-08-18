"""Shared fixtures for finalize tests — proven run-scoped identity (PRD 278)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from wave_json_io import write_json
from wave_run_adopt import compute_task_list_content_hash
from wave_run_paths import state_path
from wave_run_plan import compute_plan_hash, persist_plan, relative_plan_path


def write_task_list(tmp_path: Path, rel: str, body: str = "# tasks\n") -> str:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", rel], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "task list"],
        check=True,
    )
    return rel


def sample_plan(
    *,
    run_id: str,
    task_list: str,
    branch: str,
    slug: str,
) -> dict[str, Any]:
    return {
        "mode": "phase",
        "runId": run_id,
        "source_task_list": task_list,
        "target": {"branch": branch, "slug": slug},
        "items": [{"id": "1", "slug": "phase-one"}],
        "waves": [["1"]],
        "edges": [],
    }


def seed_proven_run_identity(
    tmp_path: Path,
    run_id: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Persist run-scoped plan + task-list hash so finalize identity gate passes."""
    task_list = str(state.get("source_task_list") or "")
    target = state.get("target") if isinstance(state.get("target"), dict) else {}
    branch = str(target.get("branch") or "feat/demo")
    slug = str(target.get("slug") or "demo")

    if not (tmp_path / task_list).is_file():
        write_task_list(tmp_path, task_list)

    plan = sample_plan(run_id=run_id, task_list=task_list, branch=branch, slug=slug)
    plan_hash = compute_plan_hash(plan)
    task_hash = compute_task_list_content_hash(tmp_path, task_list)
    assert task_hash is not None

    work_state = dict(state)
    work_state["planHash"] = plan_hash
    work_state["planPath"] = relative_plan_path(tmp_path, run_id)
    work_state["sourceTaskListContentHash"] = task_hash
    persist_plan(tmp_path, run_id, plan, work_state)
    write_json(state_path(tmp_path, run_id), work_state)
    return work_state
