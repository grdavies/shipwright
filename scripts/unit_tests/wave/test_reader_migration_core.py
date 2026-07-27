"""PRD 081 R18 — deliver core reader migration fixtures."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from wave_acceptance import acceptance_record_path, write_acceptance_record
from wave_merge import load_deliver_plan, select_next_merge_entry
from wave_run_paths import GLOBAL_PLAN_REL, mint_run_id, plan_path
from wave_run_plan import ensure_run_id, persist_plan
from wave_state import save_run_scoped_state


def _sample_plan(*, branch: str = "feat/workflow-state-machine-hardening") -> dict:
    return {
        "mode": "phase",
        "target": {"branch": branch, "slug": "workflow-state-machine-hardening"},
        "items": [
            {"id": "4", "slug": "reader-migration-deliver-core-readers-medium", "branch": f"{branch}-phase-reader"},
            {"id": "5", "slug": "reader-migration-auxiliary-readers-medium", "branch": f"{branch}-phase-aux"},
        ],
        "waves": [["4"], ["5"]],
        "edges": [{"from": "4", "to": "5"}],
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


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    _init_git(root)
    return root


def _persist_run(repo: Path, plan: dict | None = None) -> tuple[str, dict]:
    state: dict = {}
    run_id = ensure_run_id(repo, state)
    persist_plan(repo, run_id, plan or _sample_plan(), state)
    save_run_scoped_state(repo, run_id, state)
    return run_id, state


def _write_global_plan_trap(repo: Path) -> None:
    """Decoy global plan — must never be read by migrated readers."""
    trap = repo / GLOBAL_PLAN_REL
    trap.parent.mkdir(parents=True, exist_ok=True)
    trap.write_text(
        json.dumps({"mode": "phase", "target": {"branch": "feat/trap"}, "edges": []}),
        encoding="utf-8",
    )


def test_merge_reader_uses_run_scoped_plan_without_global_fallback(repo: Path) -> None:
    run_id, state = _persist_run(repo)
    _write_global_plan_trap(repo)

    plan = load_deliver_plan(repo, state)
    assert plan["target"]["branch"] == "feat/workflow-state-machine-hardening"
    assert plan_path(repo, run_id).is_file()
    assert not (repo / GLOBAL_PLAN_REL).read_text().startswith(
        json.dumps(plan, sort_keys=True)[:20]
    )


def test_merge_queue_resolves_edges_from_run_scoped_plan(repo: Path) -> None:
    run_id, state = _persist_run(repo)
    _write_global_plan_trap(repo)
    state["mergeQueue"] = [
        {"phaseSlug": "reader-migration-auxiliary-readers-medium"},
    ]
    state["mergedPhases"] = [{"phaseSlug": "reader-migration-deliver-core-readers-medium"}]
    state["phases"] = {
        "4": {"slug": "reader-migration-deliver-core-readers-medium", "status": "green-merged"},
        "5": {"slug": "reader-migration-auxiliary-readers-medium", "status": "pending"},
    }

    entry, _queue = select_next_merge_entry(state, repo)
    assert entry is not None
    assert entry.get("phaseSlug") == "reader-migration-auxiliary-readers-medium"
    assert plan_path(repo, run_id).is_file()


def test_lifecycle_load_plan_requires_run_scoped_state(repo: Path) -> None:
    import wave_lifecycle

    run_id, state = _persist_run(repo)
    _write_global_plan_trap(repo)

    plan = wave_lifecycle.load_plan(repo, None, state=state)
    assert plan["target"]["branch"] == "feat/workflow-state-machine-hardening"
    assert plan_path(repo, run_id).is_file()


def test_lifecycle_rejects_repository_global_plan_path(repo: Path) -> None:
    import wave_lifecycle

    _, state = _persist_run(repo)
    _write_global_plan_trap(repo)

    with pytest.raises(SystemExit):
        wave_lifecycle.load_plan(repo, GLOBAL_PLAN_REL, state=state)


def test_terminal_docs_currency_paths_resolve_run_scoped_plan(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from wave_terminal import resolve_docs_currency_paths

    run_id, state = _persist_run(repo)
    _write_global_plan_trap(repo)
    save_run_scoped_state(repo, run_id, state)

    monkeypatch.setattr(
        "wave_state.load_deliver_state",
        lambda _root, **_: state,
    )
    _root, _wt, _state_path, resolved_plan = resolve_docs_currency_paths(repo)

    assert resolved_plan == plan_path(repo, run_id)
    assert resolved_plan.is_file()
    assert resolved_plan != repo / GLOBAL_PLAN_REL


def test_terminal_acceptance_record_is_run_scoped(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "merge_ready_enforcement.mandatory_gate_ids",
        lambda _root: [],
    )
    run_id, state = _persist_run(repo)
    _write_global_plan_trap(repo)
    state["source_task_list"] = "docs/prds/081-workflow-state-machine-hardening/tasks.md"
    state["mergedPhases"] = [
        {
            "phaseSlug": "reader-migration-deliver-core-readers-medium",
            "phaseId": "4",
            "mergeCommit": "a" * 40,
        }
    ]
    state["phases"] = {
        "4": {"slug": "reader-migration-deliver-core-readers-medium", "status": "green-merged"},
    }

    path = write_acceptance_record(repo, state)
    assert path is not None
    assert path == acceptance_record_path(repo, state)
    assert run_id in str(path)
    assert GLOBAL_PLAN_REL not in str(path)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["runId"] == run_id
