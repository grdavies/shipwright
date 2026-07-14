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

# --- PRD 068 R6–R9 absorb / closure audit ---


def _fixture_closure_repo(tmp_path: Path, monkeypatch) -> tuple[Path, dict, FixtureIssuesStore, str]:
    from issues_lib import FixtureIssuesStore
    from planning_canonical import compose_issue_body, FROZEN_LABEL, status_label

    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-068"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor/workflow.config.json").write_text(__import__("json").dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    prd_unit = "068-prd-post-067-dogfood-hardening"
    gap_unit = "gap-153-absorb-discovery"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        (
            f"---\nid: {prd_unit}\ntype: prd\nstatus: complete\n"
            f"planningIssues: planning#153\nvisibility: public\n---\n# PRD 068\n"
        ),
    )
    gap_body = compose_issue_body(
        project_key,
        "gap",
        gap_unit,
        (
            f"---\nid: {gap_unit}\ntype: gap\nstatus: scheduled\n"
            f"schedule: PRD 068\nabsorbed-by: {prd_unit}\nrelated: planning#153\n"
            f"visibility: public\n---\n# Gap 153\n"
        ),
    )
    prd_rec = store.create(
        title="PRD 068",
        body=prd_body,
        labels=["sw:prd", status_label("complete"), f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    gap_rec = store.create(
        title="Gap 153",
        body=gap_body,
        labels=["sw:gap", "sw:gap-scheduled", f"sw:unit:{gap_unit}"],
        project_key=project_key,
        artifact_type="gap",
        unit_id=gap_unit,
    )
    gap_rec.number = 153
    store._issues[gap_rec.id] = gap_rec
    store._persist()
    index = {
        "version": 1,
        "units": {
            f"{project_key}:{prd_unit}": prd_rec.id,
            f"{project_key}:{gap_unit}": gap_rec.id,
        },
    }
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        __import__("json").dumps(index), encoding="utf-8"
    )
    return root, cfg, store, prd_unit


def test_planning_issues_discovery_hybrid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R7 — planningIssues ref discovers gap when absorbs empty."""
    from planning_store import resolve_delivery_linked_units

    root, cfg, _store, prd_unit = _fixture_closure_repo(tmp_path, monkeypatch)
    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    assert snap["verdict"] == "ok", snap
    gap_ids = [item["unitId"] for item in snap["snapshot"] if item["artifactType"] == "gap"]
    assert "gap-153-absorb-discovery" in gap_ids


def test_foreign_planning_issue_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R7 — bare foreign planningIssues without provenance are skipped."""
    from issues_lib import FixtureIssuesStore
    from planning_canonical import compose_issue_body
    from planning_store import resolve_delivery_linked_units

    root, cfg, store, prd_unit = _fixture_closure_repo(tmp_path, monkeypatch)
    prd_rec = store.find_by_unit("closure-068", prd_unit)
    assert prd_rec is not None
    foreign = compose_issue_body(
        "closure-068",
        "gap",
        "gap-999-foreign",
        "---\nid: gap-999-foreign\ntype: gap\nstatus: open\n---\n# foreign\n",
    )
    foreign_rec = store.create(
        title="foreign",
        body=foreign,
        labels=["sw:gap", "sw:gap-open", "sw:unit:gap-999-foreign"],
        project_key="closure-068",
        artifact_type="gap",
        unit_id="gap-999-foreign",
    )
    foreign_rec.number = 999
    store._issues[foreign_rec.id] = foreign_rec
    store._persist()
    body = prd_rec.body.replace("planning#153", "planning#153, planning#999")
    store.update(prd_rec.id, body=body)
    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    assert snap["verdict"] == "ok", snap
    gap_ids = [item["unitId"] for item in snap["snapshot"] if item["artifactType"] == "gap"]
    assert "gap-999-foreign" not in gap_ids
    assert any(item.get("reason") == "planning-issue-no-provenance" for item in snap.get("skipped", []))


def test_record_absorb_linkage_generic_writes_absorbs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R6 — generic absorb-linkage writes absorbs + schedule + absorbed-by."""
    import planning_gap_capture as pgc
    from planning_migrate_issue_store import parse_frontmatter_fields

    root, cfg, store, prd_unit = _fixture_closure_repo(tmp_path, monkeypatch)
    # reset linkage fields
    gap_unit = "gap-153-absorb-discovery"
    gap_rec = store.find_by_unit("closure-068", gap_unit)
    prd_rec = store.find_by_unit("closure-068", prd_unit)
    assert gap_rec and prd_rec
    gap_body = gap_rec.body.replace("absorbed-by: 068-prd-post-067-dogfood-hardening", "absorbed-by:")
    gap_body = gap_body.replace("status: scheduled", "status: open")
    store.update(gap_rec.id, body=gap_body, labels=["sw:gap", "sw:gap-open", f"sw:unit:{gap_unit}"])
    prd_body = prd_rec.body
    out = pgc.record_absorb_linkage(
        root,
        prd_unit_id=prd_unit,
        prd_number="068",
        gap_unit_ids=[gap_unit],
        planning_issue="planning#153",
        dry_run=False,
    )
    assert out["verdict"] == "ok", out
    import planning_store
    from planning_store import get_backend
    backend = get_backend(root, cfg, override="issue-store")
    prd_get = backend.get(prd_unit, planning_store._default_body_path(prd_unit, "prd"))
    gap_get = backend.get(gap_unit, planning_store._default_body_path(gap_unit, "gap"))
    assert prd_get.verdict == "ok" and gap_get.verdict == "ok"
    prd_fm = parse_frontmatter_fields(prd_get.content or "")
    gap_fm = parse_frontmatter_fields(gap_get.content or "")
    from planning_store import _parse_absorbs_targets
    absorbs = _parse_absorbs_targets(prd_fm.get("absorbs", ""))
    assert any("gap-153" in item for item in absorbs)
    assert gap_fm.get("absorbed-by") == prd_unit


def test_open_duplicate_tasks_fail_soft_gaps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R8 — open duplicate tasks aliases do not block gap discovery."""
    from issues_lib import FixtureIssuesStore
    from planning_canonical import compose_issue_body, FROZEN_LABEL, status_label
    from planning_store import IssueStoreBackend, resolve_delivery_linked_units

    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-068-dup"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor/workflow.config.json").write_text(__import__("json").dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    prd_unit = "068-prd-post-067-dogfood-hardening"
    tasks_a = "tasks-068-post-067-dogfood-hardening"
    tasks_b = "tasks-debug-post-067-dogfood-hardening"
    index_units = {}
    for uid in (tasks_a, tasks_b):
        body = compose_issue_body(
            project_key,
            "tasks",
            uid,
            f"---\nid: {uid}\ntype: tasks\nfrozen: true\n---\n### 1. One\n",
        )
        rec = store.create(
            title=uid,
            body=body,
            labels=["sw:tasks", f"sw:unit:{uid}"],
            project_key=project_key,
            artifact_type="tasks",
            unit_id=uid,
        )
        index_units[f"{project_key}:{uid}"] = rec.id
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        f"---\nid: {prd_unit}\ntype: prd\nabsorbs: [gap-153-absorb-discovery]\n---\n# PRD\n",
    )
    store.create(
        title="prd",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    gap_body = compose_issue_body(
        project_key,
        "gap",
        "gap-153-absorb-discovery",
        "---\nid: gap-153-absorb-discovery\ntype: gap\nstatus: open\n---\n# gap\n",
    )
    gap_rec = store.create(
        title="gap",
        body=gap_body,
        labels=["sw:gap", "sw:gap-open", "sw:unit:gap-153-absorb-discovery"],
        project_key=project_key,
        artifact_type="gap",
        unit_id="gap-153-absorb-discovery",
    )
    prd_rec = store.find_by_unit(project_key, prd_unit)
    index = {
        "version": 1,
        "units": {
            **index_units,
            f"{project_key}:{prd_unit}": prd_rec.id if prd_rec else "",
            f"{project_key}:gap-153-absorb-discovery": gap_rec.id,
        },
    }
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        __import__("json").dumps(index), encoding="utf-8"
    )
    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    assert snap.get("tasksResolution", {}).get("verdict") == "not-ready"
    assert snap["verdict"] == "ok"
    assert any(item["artifactType"] == "gap" for item in snap["snapshot"])


def test_audit_closure_open_remaining_false_green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R9 — undiscovered open gaps yield not-ready audit with resumeCommand."""
    from planning_store import audit_closure_completeness

    root, cfg, _store, prd_unit = _fixture_closure_repo(tmp_path, monkeypatch)
    audit = audit_closure_completeness(root, cfg, prd_unit)
    assert audit["verdict"] == "not-ready", audit
    assert audit["openRemaining"]
    assert audit.get("resumeCommand")


def test_duplicate_open_tasks_mint_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R8 — refuse second open tasks mint for same slug."""
    from issues_lib import FixtureIssuesStore
    from planning_canonical import compose_issue_body
    from planning_store import IssueStoreBackend

    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-068-mint"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor/workflow.config.json").write_text(__import__("json").dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    uid = "tasks-068-post-067-dogfood-hardening"
    body = compose_issue_body(
        project_key,
        "tasks",
        uid,
        f"---\nid: {uid}\ntype: tasks\n---\n### 1. One\n",
    )
    rec = store.create(
        title=uid,
        body=body,
        labels=["sw:tasks", f"sw:unit:{uid}"],
        project_key=project_key,
        artifact_type="tasks",
        unit_id=uid,
    )
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        __import__("json").dumps({"version": 1, "units": {f"{project_key}:{uid}": rec.id}}),
        encoding="utf-8",
    )
    backend = IssueStoreBackend(root, cfg)
    dup_uid = "tasks-debug-post-067-dogfood-hardening"
    dup_body = compose_issue_body(
        project_key,
        "tasks",
        dup_uid,
        f"---\nid: {dup_uid}\ntype: tasks\n---\n### 1. Dup\n",
    )
    try:
        backend.put(dup_uid, f"docs/prds/068-post-067-dogfood-hardening/{dup_uid}.md", dup_body)
        raised = False
    except SystemExit:
        raised = True
    assert raised

