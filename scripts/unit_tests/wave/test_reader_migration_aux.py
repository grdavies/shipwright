"""PRD 081 R18 — auxiliary reader migration fixtures."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from cleanup_lib import Report, _collect_terminal_run_state, enumerate_cleanup
from wave_failure import append_log, load_plan, plan_edges
from wave_json_io import write_json
from wave_memory import distill_learnings, read_run_log
from wave_living_docs import load_plan as living_load_plan, prd_number_from_state
from wave_run_paths import GLOBAL_PLAN_REL, events_path, plan_path
from wave_run_plan import ensure_run_id, persist_plan
from wave_state import scoped_paths


def _sample_plan() -> dict:
    return {
        "mode": "phase",
        "target": {"branch": "feat/demo", "slug": "demo"},
        "prd_number": "081",
        "source_task_list": "docs/prds/081/tasks.md",
        "items": [{"id": "1", "slug": "alpha"}, {"id": "2", "slug": "beta"}],
        "waves": [["1"], ["2"]],
        "edges": [{"from": "1", "to": "2"}],
        "notices": ["contention: phases 1 and 2 serialized"],
        "contention": {"injectedEdges": [{"from": "1", "to": "2", "kind": "contention"}]},
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


def _bootstrap_run_scoped(repo: Path) -> dict:
    _init_git(repo)
    plan = _sample_plan()
    state: dict = {
        "verdict": "running",
        "target": plan["target"],
        "source_task_list": plan["source_task_list"],
        "prd_number": plan["prd_number"],
        "phases": {
            "1": {"id": "1", "slug": "alpha", "status": "in-flight"},
            "2": {"id": "2", "slug": "beta", "status": "pending"},
        },
    }
    run_id = ensure_run_id(repo, state)
    persist_plan(repo, run_id, plan, state)
    branch = str(plan["target"]["branch"])
    state_file = scoped_paths(repo, branch)["state"]
    state_file.parent.mkdir(parents=True, exist_ok=True)
    write_json(state_file, state)
    assert not (repo / GLOBAL_PLAN_REL).exists()
    return state


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    return root


def test_failure_plan_reads_run_scoped_plan_without_global_fallback(repo: Path) -> None:
    state = _bootstrap_run_scoped(repo)
    edges = plan_edges(repo, state)
    assert edges == [{"from": "1", "to": "2"}]
    loaded = load_plan(repo, state)
    assert loaded["target"]["slug"] == "demo"
    assert not (repo / GLOBAL_PLAN_REL).exists()


def test_failure_append_log_writes_run_scoped_events(repo: Path) -> None:
    state = _bootstrap_run_scoped(repo)
    append_log(repo, {"event": "blast-radius", "sourcePhaseSlug": "alpha"}, state)
    run_id = state["runId"]
    log_path = events_path(repo, run_id)
    assert log_path.is_file()
    assert (repo / ".cursor" / "sw-deliver-runs" / "run.log").exists() is False
    payload = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert payload["event"] == "blast-radius"


def test_memory_prework_reads_run_scoped_plan(repo: Path) -> None:
    state = _bootstrap_run_scoped(repo)
    append_log(repo, {"event": "forward-merge-blocked", "cause": "conflict"}, state)
    payload = distill_learnings(repo)
    kinds = {item["kind"] for item in payload["patterns"]}
    assert "contention" in kinds
    assert "dependent-conflict" in kinds
    assert payload["prd_number"] == "081"
    assert not (repo / GLOBAL_PLAN_REL).exists()


def test_memory_read_run_log_uses_run_namespace(repo: Path) -> None:
    state = _bootstrap_run_scoped(repo)
    append_log(repo, {"event": "phase-revert", "phaseSlug": "alpha"}, state)
    entries = read_run_log(repo, state)
    assert entries[-1]["event"] == "phase-revert"


def test_living_docs_reads_active_run_plan(repo: Path) -> None:
    state = _bootstrap_run_scoped(repo)
    plan = living_load_plan(repo, state)
    assert plan["source_task_list"] == "docs/prds/081/tasks.md"
    assert prd_number_from_state(state, plan) == "081"
    assert not (repo / GLOBAL_PLAN_REL).exists()


def test_cleanup_enumerates_run_directories_not_global_plan(repo: Path) -> None:
    state = _bootstrap_run_scoped(repo)
    run_id = state["runId"]
    terminal_state = {**state, "verdict": "complete"}
    write_json(scoped_paths(repo, "feat/demo")["state"], terminal_state)

    report = Report(dry_run=True)
    _collect_terminal_run_state(report, repo, repo, "complete")
    rels = {item.name for item in report.would_remove}
    run_dir_rel = str(plan_path(repo, run_id).parent.relative_to(repo))
    assert run_dir_rel in rels
    assert GLOBAL_PLAN_REL not in rels
    assert ".cursor/sw-deliver-runs" not in rels

    full = enumerate_cleanup(repo)
    assert not any(
        item.name == GLOBAL_PLAN_REL for item in full.would_remove + full.protected
    )


def test_unmigrated_global_plan_fallback_fails_for_failure_reader(repo: Path) -> None:
    _init_git(repo)
    global_plan = _sample_plan()
    (repo / GLOBAL_PLAN_REL).parent.mkdir(parents=True, exist_ok=True)
    (repo / GLOBAL_PLAN_REL).write_text(json.dumps(global_plan), encoding="utf-8")
    state = {
        "verdict": "running",
        "target": global_plan["target"],
        "phases": {"1": {"slug": "alpha", "status": "blocked", "cause": "verify:failed"}},
    }
    write_json(scoped_paths(repo, "feat/demo")["state"], state)

    with pytest.raises(SystemExit) as exc:
        load_plan(repo, state)
    assert exc.value.code == 2
