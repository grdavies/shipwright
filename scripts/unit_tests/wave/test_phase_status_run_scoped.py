"""PRD 081 R20 — run-namespaced status discovery and concurrent-slug isolation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from halt_resume import resolve_run_id
from phase_status_discovery import (
    collect_status_candidate_paths,
    discover_phase_status,
    first_existing_status_path,
    preferred_phase_artifact_path,
    resolve_run_and_phase_id,
)
from wave_acceptance import (
    acceptance_record_path,
    blocker_record_path,
    read_acceptance_record,
    write_acceptance_record,
    write_blocker_record,
    write_phase_blocker_record,
)
from wave_json_io import write_json
from wave_run_paths import mint_run_id, phase_directory, plan_path, terminal_acceptance_path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    return root


def _phase_state(
    run_id: str,
    phase_id: str,
    phase_slug: str,
    *,
    worktree: Path | None = None,
) -> dict:
    state: dict = {
        "runId": run_id,
        "source_task_list": "docs/prds/081/tasks.md",
        "target": {"branch": "feat/workflow-state-machine-hardening"},
        "phases": {
            phase_id: {
                "id": phase_id,
                "slug": phase_slug,
                "status": "in-flight",
            }
        },
    }
    if worktree is not None:
        state["phaseWorktrees"] = {phase_id: {"path": str(worktree)}}
    return state


def test_resolve_run_and_phase_id_uses_slug_lookup_only(repo: Path) -> None:
    run_a = mint_run_id(repo)
    state = _phase_state(run_a, "7", "shared-slug")
    assert resolve_run_and_phase_id(state, "shared-slug") == (run_a, "7")
    assert resolve_run_and_phase_id(state, "missing-slug") is None


def test_discovery_paths_exclude_glob_and_slug_keys(repo: Path) -> None:
    run_id = mint_run_id(repo)
    phase_id = "7"
    slug = "shared-slug"
    state = _phase_state(run_id, phase_id, slug)

    stale_slug_dir = repo / ".cursor" / "sw-deliver-runs" / slug
    stale_slug_dir.mkdir(parents=True)
    write_json(stale_slug_dir / "status.json", {"verdict": "merge-ready-green", "head": "a" * 40})

    wt_root = repo / ".sw-worktrees" / "other-phase"
    wt_root.mkdir(parents=True)
    glob_stale = (
        wt_root
        / ".cursor"
        / "sw-deliver-runs"
        / slug
        / "status.json"
    )
    glob_stale.parent.mkdir(parents=True)
    write_json(glob_stale, {"verdict": "blocked", "head": "b" * 40})

    canonical = phase_directory(repo, run_id, phase_id) / "status.json"
    canonical.parent.mkdir(parents=True)
    write_json(canonical, {"verdict": "merge-ready-green", "head": "c" * 40})

    paths = collect_status_candidate_paths(repo, slug, "status.json", state=state)
    assert paths == [canonical]
    assert glob_stale not in paths
    assert stale_slug_dir / "status.json" not in paths

    path, doc = discover_phase_status(repo, slug, "status.json", state=state)
    assert path == canonical
    assert doc is not None
    assert doc.get("head") == "c" * 40


def test_concurrent_slug_runs_keep_isolated_status_and_acceptance(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "merge_ready_enforcement.mandatory_gate_ids",
        lambda _root: [],
    )
    slug = "shared-slug"
    run_a = mint_run_id(repo)
    run_b = mint_run_id(repo)
    state_a = _phase_state(run_a, "7", slug)
    state_b = _phase_state(run_b, "7", slug)

    status_a = phase_directory(repo, run_a, "7") / "status.json"
    status_b = phase_directory(repo, run_b, "7") / "status.json"
    status_a.parent.mkdir(parents=True)
    status_b.parent.mkdir(parents=True)
    write_json(status_a, {"verdict": "merge-ready-green", "head": "a" * 40})
    write_json(status_b, {"verdict": "blocked", "head": "b" * 40, "cause": "verify:red"})

    plan_a = plan_path(repo, run_a)
    plan_b = plan_path(repo, run_b)
    write_json(plan_a, {"run": "a"})
    write_json(plan_b, {"run": "b"})
    assert json.loads(plan_a.read_text()) != json.loads(plan_b.read_text())

    write_blocker_record(repo, state_a, {"verdict": "halt", "haltResume": {"runId": run_a}})
    write_blocker_record(repo, state_b, {"verdict": "halt", "haltResume": {"runId": run_b}})
    assert blocker_record_path(repo, state_a) != blocker_record_path(repo, state_b)

    write_phase_blocker_record(repo, state_a, slug, {"phase": "a"})
    write_phase_blocker_record(repo, state_b, slug, {"phase": "b"})
    assert (phase_directory(repo, run_a, "7") / "blocker.json").is_file()
    assert (phase_directory(repo, run_b, "7") / "blocker.json").is_file()

    write_acceptance_record(repo, state_a)
    write_acceptance_record(repo, state_b)
    acc_a = read_acceptance_record(repo, state_a)
    acc_b = read_acceptance_record(repo, state_b)
    assert acc_a is not None and acc_b is not None
    assert acc_a["runId"] == run_a
    assert acc_b["runId"] == run_b
    assert acceptance_record_path(repo, state_a) != acceptance_record_path(repo, state_b)

    _, doc_a = discover_phase_status(repo, slug, "status.json", state=state_a)
    _, doc_b = discover_phase_status(repo, slug, "status.json", state=state_b)
    assert doc_a and doc_a.get("verdict") == "merge-ready-green"
    assert doc_b and doc_b.get("verdict") == "blocked"


def test_stale_worktree_status_not_discovered_by_new_run(repo: Path) -> None:
    slug = "shared-slug"
    old_run = mint_run_id(repo)
    new_run = mint_run_id(repo)
    worktree = repo / ".sw-worktrees" / "phase-wt"
    worktree.mkdir(parents=True)

    stale = worktree / ".cursor" / "sw-deliver-runs" / slug / "status.json"
    stale.parent.mkdir(parents=True)
    write_json(
        stale,
        {"verdict": "merge-ready-green", "head": "d" * 40, "phase": slug},
    )

    state = _phase_state(new_run, "7", slug, worktree=worktree)
    canonical = phase_directory(repo, new_run, "7") / "status.json"
    canonical.parent.mkdir(parents=True)
    write_json(canonical, {"verdict": "blocked", "head": "e" * 40})

    paths = collect_status_candidate_paths(repo, slug, "status.json", state=state)
    mirror = paths[1]
    assert stale.resolve() != mirror.resolve()
    assert not mirror.is_file()

    path, doc = discover_phase_status(repo, slug, "status.json", state=state)
    assert path == canonical
    assert doc and doc.get("verdict") == "blocked"


def test_reintroduced_glob_does_not_affect_discovery(repo: Path) -> None:
    run_id = mint_run_id(repo)
    slug = "glob-slug"
    state = _phase_state(run_id, "3", slug)

    canonical = preferred_phase_artifact_path(repo, slug, "gap-check.status.json", state=state)
    canonical.parent.mkdir(parents=True)
    write_json(canonical, {"verdict": "pass", "binding": True, "head": "f" * 40})

    wt_root = repo / ".sw-worktrees" / "legacy-wt"
    glob_hit = wt_root / ".cursor" / "sw-deliver-runs" / slug / "gap-check.status.json"
    glob_hit.parent.mkdir(parents=True)
    write_json(glob_hit, {"verdict": "halt", "binding": True, "cause": "gap-check:stale"})

    paths = collect_status_candidate_paths(repo, slug, "gap-check.status.json", state=state)
    assert len(paths) == 1
    assert paths[0] == canonical

    path, doc = discover_phase_status(repo, slug, "gap-check.status.json", state=state)
    assert path == canonical
    assert doc and doc.get("verdict") == "pass"


def test_first_existing_prefers_canonical_run_scoped_path(repo: Path) -> None:
    run_id = mint_run_id(repo)
    slug = "write-slug"
    state = _phase_state(run_id, "9", slug)
    chosen = first_existing_status_path(repo, slug, "status.json", state=state)
    assert chosen == phase_directory(repo, run_id, "9") / "status.json"
    assert resolve_run_id(state) == run_id
    assert terminal_acceptance_path(repo, run_id) == acceptance_record_path(repo, state)
