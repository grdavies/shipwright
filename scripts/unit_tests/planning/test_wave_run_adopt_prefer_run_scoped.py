"""Prefer run-scoped adopt under foreign global plan (PRD 278 R3–R5)."""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_json_io import read_json, write_json
from wave_run_adopt import (
    acquire_adopt_lock,
    adopt_legacy_run,
    adopt_lock_path,
    assess_proven_run_scoped_identity,
    compute_task_list_content_hash,
    locate_legacy_source,
    preview_adoption,
    release_adopt_lock,
)
from wave_run_paths import global_plan_path, plan_path, state_path
from wave_run_plan import compute_plan_hash, persist_plan, relative_plan_path


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)


def _sample_plan(slug: str = "alpha", *, run_id: str | None = None) -> dict:
    return {
        "mode": "phase",
        "runId": run_id or f"deliver-{slug}",
        "source_task_list": f"docs/prds/081-{slug}/tasks-081-{slug}.md",
        "target": {"branch": f"feat/{slug}", "slug": slug},
        "items": [{"id": "1", "slug": "phase-one"}],
        "waves": [["1"]],
        "edges": [],
    }


def _write_task_list(tmp_path: Path, rel: str, body: str = "# tasks\n") -> str:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", rel], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-q", "-m", "task list"],
        check=True,
    )
    return rel


def _legacy_fixture_with_run_scoped_plan(
    tmp_path: Path,
    slug: str = "alpha",
    *,
    foreign_global: bool = False,
) -> dict:
    task_rel = _write_task_list(tmp_path, f"docs/prds/081-{slug}/tasks-081-{slug}.md")
    plan = _sample_plan(slug)
    plan_hash = compute_plan_hash(plan)
    run_id = f"deliver-{slug}"
    task_hash = compute_task_list_content_hash(tmp_path, task_rel)
    assert task_hash is not None
    state = {
        "verdict": "running",
        "runId": run_id,
        "source_task_list": task_rel,
        "sourceTaskListContentHash": task_hash,
        "target": plan["target"],
        "phases": {"1": {"status": "pending"}},
        "nextAction": "provision-phase",
        "planHash": plan_hash,
        "planPath": relative_plan_path(tmp_path, run_id),
    }
    scoped = tmp_path / ".cursor" / f"sw-deliver-state.{slug}.json"
    scoped.parent.mkdir(parents=True, exist_ok=True)
    write_json(scoped, state)
    persist_plan(tmp_path, run_id, plan, state)
    if foreign_global:
        foreign = _sample_plan("foreign-other", run_id="deliver-foreign-other")
        write_json(global_plan_path(tmp_path), foreign)
    else:
        write_json(global_plan_path(tmp_path), plan)
    return {
        "state": state,
        "scoped": scoped,
        "plan": plan,
        "planHash": plan_hash,
        "runId": run_id,
        "taskHash": task_hash,
    }


def test_prefer_run_scoped_under_foreign_global_plan(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    fixture = _legacy_fixture_with_run_scoped_plan(tmp_path, foreign_global=True)
    source = locate_legacy_source(tmp_path, slug="alpha")
    assert source is not None
    preview = preview_adoption(tmp_path, source)
    assert preview["foreignGlobalPlan"] is True
    assert preview["preferRunScopedPlan"] is True
    assert preview["planHashMismatch"] is False
    result = adopt_legacy_run(tmp_path, source)
    assert result["preferRunScopedPlan"] is True
    assert result["planSource"] == "run-scoped"
    adopted = read_json(state_path(tmp_path, fixture["runId"]))
    assert adopted.get("legacyAdopted") is True
    assert adopted.get("adoptedPlanHash") == fixture["planHash"]
    assert adopted.get("sourceTaskListContentHash") == fixture["taskHash"]


def test_unproven_identity_refuses_when_plan_missing(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    fixture = _legacy_fixture_with_run_scoped_plan(tmp_path, foreign_global=True)
    plan_path(tmp_path, fixture["runId"]).unlink(missing_ok=True)
    assessment = assess_proven_run_scoped_identity(
        tmp_path, fixture["state"], run_id=fixture["runId"]
    )
    assert assessment["proven"] is False
    assert assessment["cause"] == "adopt:run-scoped-plan-missing"


def test_foreign_global_without_run_scoped_plan_still_uses_global_when_matching(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    plan = _sample_plan("beta")
    plan_hash = compute_plan_hash(plan)
    task_rel = _write_task_list(tmp_path, plan["source_task_list"])
    task_hash = compute_task_list_content_hash(tmp_path, task_rel)
    state = {
        "verdict": "running",
        "runId": "deliver-beta",
        "source_task_list": task_rel,
        "sourceTaskListContentHash": task_hash,
        "target": plan["target"],
        "phases": {"1": {"status": "pending"}},
        "planHash": plan_hash,
    }
    scoped = tmp_path / ".cursor" / "sw-deliver-state.beta.json"
    write_json(scoped, state)
    write_json(global_plan_path(tmp_path), plan)
    source = locate_legacy_source(tmp_path, slug="beta")
    assert source is not None
    result = adopt_legacy_run(tmp_path, source)
    assert result["planSource"] == "global"


def test_adopt_lock_cas_blocks_concurrent_foreign_global_race(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    fixture = _legacy_fixture_with_run_scoped_plan(tmp_path, foreign_global=True)
    source = locate_legacy_source(tmp_path, slug="alpha")
    assert source is not None
    held = acquire_adopt_lock(tmp_path, fixture["runId"])
    assert held["verdict"] == "pass"
    results: list[dict] = []

    def attempt() -> None:
        try:
            adopt_legacy_run(tmp_path, source)
            results.append({"ok": True})
        except BaseException as exc:
            results.append({"ok": False, "code": getattr(exc, "code", None), "type": type(exc).__name__})

    thread = threading.Thread(target=attempt)
    thread.start()
    thread.join(timeout=5)
    release_adopt_lock(Path(str(held["lockPath"])))
    assert results
    assert results[0]["ok"] is False
    result = adopt_legacy_run(tmp_path, source)
    assert result["verdict"] == "pass"
