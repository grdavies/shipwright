"""Regression tests for gap-112 post-deliver closure completeness (PRD 060 R4–R7)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from issues_lib import FixtureIssuesStore
from planning_progress import phase_done_label, sync_phase_done
from planning_store import (
    IssueStoreBackend,
    _gap_closure_evidence,
    _prd_unit_id_alias_candidates,
    _slug_from_prd_unit,
    _tasks_unit_id_candidates,
    close_delivery_units,
    close_done_phase_sub_issues,
    resolve_delivery_linked_units,
)
import planning_progress as pp


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "closure-060") -> dict:
    return {
        "version": 1,
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": project_key,
                "hierarchy": {"epicSubIssues": True},
            }
        },
        "host": {"provider": "github"},
    }


@pytest.mark.parametrize(
    ("unit_id", "expected"),
    [
        ("060-prd-alpha", {"060-prd-alpha", "prd-060-alpha", "060-alpha"}),
        ("prd-060-alpha", {"prd-060-alpha", "060-prd-alpha", "060-alpha"}),
        ("060-alpha", {"060-alpha", "060-prd-alpha", "prd-060-alpha"}),
    ],
)
def test_prd_unit_id_alias_candidates(unit_id: str, expected: set[str]) -> None:
    assert set(_prd_unit_id_alias_candidates(unit_id)) == expected


@pytest.mark.parametrize(
    ("unit_id", "prd_num", "expected_slug"),
    [
        ("062-prd-deliver-issue-store-hardening-and-loop-perf", "062", "deliver-issue-store-hardening-and-loop-perf"),
        ("prd-062-deliver-issue-store-hardening-and-loop-perf", "062", "deliver-issue-store-hardening-and-loop-perf"),
        ("062-deliver-issue-store-hardening-and-loop-perf", "062", "deliver-issue-store-hardening-and-loop-perf"),
    ],
)
def test_slug_from_prd_unit_canonical_nnn_prd_slug(unit_id: str, prd_num: str, expected_slug: str) -> None:
    assert _slug_from_prd_unit(unit_id, prd_num) == expected_slug


def test_tasks_unit_id_candidates_exclude_prd_unit_alias() -> None:
    prd_unit = "062-prd-deliver-issue-store-hardening-and-loop-perf"
    candidates = _tasks_unit_id_candidates(prd_unit, "062")
    assert "tasks-062-deliver-issue-store-hardening-and-loop-perf" in candidates
    assert prd_unit not in candidates


def test_resolve_delivery_linked_units_resolves_tasks_not_prd_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg("closure-062-tasks-alias")
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")

    prd_unit = "062-prd-deliver-issue-store-hardening-and-loop-perf"
    tasks_unit = "tasks-062-deliver-issue-store-hardening-and-loop-perf"
    slug = "deliver-issue-store-hardening-and-loop-perf"
    prd_dir = root / "docs" / "prds" / f"062-{slug}"
    prd_dir.mkdir(parents=True)
    prd_path = f"docs/prds/062-{slug}/{prd_unit}.md"
    tasks_path = f"docs/prds/062-{slug}/{tasks_unit}.md"
    prd_content = (
        f"---\ntype: prd\nid: {prd_unit}\nstatus: complete\n---\n# PRD 062\n"
    )
    tasks_content = "---\nfrozen: true\n---\n### 1. Phase one\n- [ ] 1.1 First\n"

    backend = IssueStoreBackend(root, cfg)
    assert backend.put(prd_unit, prd_path, prd_content).verdict == "ok"
    assert backend.put(tasks_unit, tasks_path, tasks_content).verdict == "ok"

    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    assert snap["verdict"] == "ok", snap
    tasks_entries = [item for item in snap["snapshot"] if item["artifactType"] == "tasks"]
    assert len(tasks_entries) == 1
    assert tasks_entries[0]["unitId"] == tasks_unit


def test_gap_closure_evidence_skips_related_only() -> None:
    fm = {"absorbs": "gap-absorbed"}
    edges = {
        "edges": [
            {"target": "gap-absorbed", "rel": "absorbs"},
            {"target": "gap-related", "rel": "depends"},
        ]
    }
    delivery, skipped = _gap_closure_evidence(fm, edges, None, Path("."), {})
    assert "gap-absorbed" in delivery
    assert "gap-related" not in delivery
    assert any(item["unitId"] == "gap-related" for item in skipped)


def test_close_done_phase_sub_issues_from_hierarchy_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg()
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")

    (root / "docs" / "prds" / "060-test").mkdir(parents=True)
    prd_path = "docs/prds/060-test/prd-060-test.md"
    (root / prd_path).write_text(
        "---\ntype: prd\nid: 060-prd-test\nstatus: in-progress\n---\n# PRD\n",
        encoding="utf-8",
    )
    backend = IssueStoreBackend(root, cfg)
    assert backend.put("060-prd-test", prd_path, (root / prd_path).read_text(encoding="utf-8")).verdict == "ok"

    task_rel = "docs/prds/060-test/tasks-060-test.md"
    (root / task_rel).write_text(
        "---\nfrozen: true\n---\n### 1. Alpha phase\n- [ ] 1.1 First\n",
        encoding="utf-8",
    )
    state = {"source_task_list": task_rel}
    pp.provision_deliver_hierarchy(root, state)
    hmap = state["hierarchyMap"]
    phase1 = hmap["phases"]["1"]
    sync_phase_done(root, state, "1")

    fixture_path = root / ".cursor/hooks/state/issue-store-fixture.json"
    store = FixtureIssuesStore(fixture_path)
    issue = store.get(str(phase1["issueId"]))
    assert phase_done_label("1") in issue.labels

    out = close_done_phase_sub_issues(
        root,
        cfg,
        "060-prd-test",
        state=state,
        dry_run=False,
    )
    assert out["verdict"] == "ready", out
    assert any(item.get("unitId", "").endswith("-phase-1") for item in out["closed"])
    reloaded = FixtureIssuesStore(fixture_path)
    closed_issue = reloaded.get(str(phase1["issueId"]))
    assert closed_issue.state == "closed"


def test_close_delivery_units_report_shape_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg("closure-report")
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (root / "docs" / "prds" / "060-report").mkdir(parents=True)
    task_rel = "docs/prds/060-report/tasks-060-report.md"
    (root / task_rel).write_text("---\nfrozen: true\n---\n### 1. One\n", encoding="utf-8")
    state = {"source_task_list": task_rel}
    pp.provision_deliver_hierarchy(root, state)

    out = close_delivery_units(root, cfg, "060-prd-report", state=state, dry_run=True)
    assert out["verdict"] == "dry-run"
    assert "considered" in out
    assert "closed" in out
    assert "skipped" in out
    assert "resumeCommand" in out

def test_build_chain_check_leaves_worktree_clean(repo_root: Path) -> None:
    """R15(k): --check must not leave dist/ mutated."""
    before = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain", "dist"],
        capture_output=True,
        text=True,
    ).stdout
    subprocess.run(
        ["python3", "scripts/build-chain-sync.py", "--check"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    after = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain", "dist"],
        capture_output=True,
        text=True,
    ).stdout
    assert before == after


def test_finalize_does_not_outer_acquire_living_doc_lock(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PRD 067 R1: finalize must not outer-acquire; reconcile owns the lock."""
    import wave_living_doc_lock
    import wave_deliver_loop as wdl

    acquires: list[str] = []

    def _try_acquire(*a, **k):
        acquires.append(str(k.get("holder") or "unknown"))
        return True

    monkeypatch.setattr(wave_living_doc_lock, "try_acquire", _try_acquire)
    monkeypatch.setattr(wave_living_doc_lock, "release", lambda *a, **k: None)
    monkeypatch.setattr(
        wdl,
        "run_wave",
        lambda *a, **k: (
            (0, {"verdict": "pass"})
            if a and a[0] == "completion"
            else (0, {"verdict": "pass"})
        ),
    )
    # run_wave is called as run_wave(root, *living_args) — first positional after root is cmd
    calls: list[tuple] = []

    def _run_wave(root, *args):
        calls.append(args)
        return 0, {"verdict": "pass"}

    monkeypatch.setattr(wdl, "run_wave", _run_wave)
    monkeypatch.setattr(wdl, "save_state", lambda root, state: None)
    monkeypatch.setattr(wdl, "load_state", lambda root: {"target": {"branch": "feat/x"}})
    monkeypatch.setattr(wdl, "orchestrator_worktree_path", lambda root, state: None)
    monkeypatch.setattr(wdl, "run_inflight_signal", lambda *a, **k: (0, {"verdict": "pass"}))
    # Avoid close_delivery_units / living doc follow-on failures
    import planning_store as ps

    monkeypatch.setattr(ps, "close_delivery_units", lambda *a, **k: {"verdict": "ok", "skipped": True})
    monkeypatch.setattr(wdl, "persist_cursor", lambda *a, **k: None)

    state = {"target": {"branch": "feat/x", "slug": "x"}, "verdict": "running"}
    # May SystemExit on later finalize steps; assert no outer acquire regardless
    try:
        wdl.execute_mechanical(
            repo_root,
            state,
            {},
            {"action": "finalize-completion"},
        )
    except SystemExit:
        pass
    assert "living-docs-reconcile-finalize" not in acquires
    assert any(args and args[0] == "living-docs" for args in calls)


def test_close_parent_epic_blocks_declared_partial(tmp_path: Path) -> None:
    """R15(m): declared-partial phase blocks parent epic close."""
    from planning_store import close_parent_epic_if_complete

    state = {
        "hierarchyMap": {
            "applied": True,
            "mode": "parent-checkbox",
            "epicIssueId": "epic-1",
            "phases": {"1": {"phaseId": "1"}},
        },
        "phases": {"1": {"status": "teardown-complete"}},
        "taskLedger": {"phases": {"1": {"declaredPartial": True}}},
    }
    out = close_parent_epic_if_complete(
        tmp_path,
        _issue_store_cfg(),
        state,
        dry_run=False,
        merged_to_main=True,
    )
    assert out["verdict"] == "blocked"
    assert out["reason"] == "declared-partial-phase"


def test_close_parent_epic_idempotent_when_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R15(m): parent epic close is idempotent when already closed."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    from issues_lib import FixtureIssuesStore
    from planning_store import close_parent_epic_if_complete

    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg("closure-epic")
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    fixture_path = root / ".cursor/hooks/state/issue-store-fixture.json"
    store = FixtureIssuesStore(fixture_path)
    epic = store.create(
        title="Epic",
        body="body",
        labels=[],
        project_key="closure-epic",
        artifact_type="epic",
        unit_id="epic-unit",
    )
    epic.state = "closed"
    store._issues[epic.id] = epic
    store._persist()
    state = {
        "hierarchyMap": {
            "applied": True,
            "mode": "parent-checkbox",
            "epicIssueId": epic.id,
            "phases": {"1": {"phaseId": "1"}},
        },
        "phases": {"1": {"status": "teardown-complete"}},
        "taskLedger": {"phases": {}},
    }
    out = close_parent_epic_if_complete(
        root, cfg, state, dry_run=False, merged_to_main=True
    )
    assert out.get("idempotent") is True
    assert out.get("action") == "noop"
