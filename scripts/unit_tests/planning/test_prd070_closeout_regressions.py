"""PRD 070 phase 1 — anchored discovery + fail-closed audit regressions."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body
from planning_canonical import FROZEN_LABEL, status_label
from planning_store import (
    IssueStoreBackend,
    audit_closure_completeness,
    discover_absorbed_units_anchored,
    normalize_task_ref,
    reconcile_ledger_task_refs,
    resolve_delivery_linked_units,
    resolve_task_ref_aliases,
)


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "closure-070") -> dict:
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


def test_prose_mention_not_absorbed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R22 — prose mention of a gap unit id is not treated as absorbed."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-070-prose"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_unit = "070-prd-closeout-anchored"
    gap_unit = "gap-070-prose-only"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        (
            f"---\nid: {prd_unit}\ntype: prd\nstatus: complete\n---\n"
            f"# PRD 070\n\nThis document references {gap_unit} in passing only.\n"
        ),
    )
    gap_body = compose_issue_body(
        project_key,
        "gap",
        gap_unit,
        f"---\nid: {gap_unit}\ntype: gap\nstatus: open\nschedule: PRD 070\n---\n# gap\n",
    )
    prd_rec = store.create(
        title="prd",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    gap_rec = store.create(
        title="gap",
        body=gap_body,
        labels=["sw:gap", "sw:gap-open", f"sw:unit:{gap_unit}"],
        project_key=project_key,
        artifact_type="gap",
        unit_id=gap_unit,
    )
    index = {
        "version": 1,
        "units": {
            f"{project_key}:{prd_unit}": prd_rec.id,
            f"{project_key}:{gap_unit}": gap_rec.id,
        },
    }
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps(index), encoding="utf-8"
    )

    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    assert snap["verdict"] == "ok", snap
    gap_ids = [item["unitId"] for item in snap["snapshot"] if item["artifactType"] == "gap"]
    assert gap_unit not in gap_ids


def test_schedule_label_without_anchor_not_absorbed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R1 — schedule labels alone do not discover absorbed gaps."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-070-schedule"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_unit = "070-prd-schedule-only"
    gap_unit = "gap-070-scheduled-unanchored"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        f"---\nid: {prd_unit}\ntype: prd\nstatus: complete\n---\n# PRD\n",
    )
    gap_body = compose_issue_body(
        project_key,
        "gap",
        gap_unit,
        f"---\nid: {gap_unit}\ntype: gap\nstatus: scheduled\nschedule: PRD 070\n---\n# gap\n",
    )
    prd_rec = store.create(
        title="prd",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    gap_rec = store.create(
        title="gap",
        body=gap_body,
        labels=["sw:gap", "sw:gap-scheduled", f"sw:unit:{gap_unit}"],
        project_key=project_key,
        artifact_type="gap",
        unit_id=gap_unit,
    )
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "units": {
                    f"{project_key}:{prd_unit}": prd_rec.id,
                    f"{project_key}:{gap_unit}": gap_rec.id,
                },
            }
        ),
        encoding="utf-8",
    )

    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    gap_ids = [item["unitId"] for item in snap.get("snapshot", []) if item.get("artifactType") == "gap"]
    assert gap_unit not in gap_ids


def test_anchored_absorbs_marker_discovers_gap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R1 — absorbs frontmatter marker discovers the gap unit."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-070-anchor"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_unit = "070-prd-anchored-absorbs"
    gap_unit = "gap-070-anchored-target"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        f"---\nid: {prd_unit}\ntype: prd\nabsorbs: {gap_unit}\n---\n# PRD\n",
    )
    gap_body = compose_issue_body(
        project_key,
        "gap",
        gap_unit,
        f"---\nid: {gap_unit}\ntype: gap\nstatus: open\n---\n# gap\n",
    )
    prd_rec = store.create(
        title="prd",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    gap_rec = store.create(
        title="gap",
        body=gap_body,
        labels=["sw:gap", "sw:gap-open", f"sw:unit:{gap_unit}"],
        project_key=project_key,
        artifact_type="gap",
        unit_id=gap_unit,
    )
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "units": {
                    f"{project_key}:{prd_unit}": prd_rec.id,
                    f"{project_key}:{gap_unit}": gap_rec.id,
                },
            }
        ),
        encoding="utf-8",
    )

    discovered, _skipped = discover_absorbed_units_anchored({"absorbs": gap_unit}, None)
    assert gap_unit in discovered

    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    gap_ids = [item["unitId"] for item in snap["snapshot"] if item["artifactType"] == "gap"]
    assert gap_unit in gap_ids


def test_audit_fail_closed_open_absorbed_gap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R2/R13 — open absorbed gap forces not-ready audit with resumeCommand."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-070-audit"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_unit = "070-prd-audit-open"
    gap_unit = "gap-070-audit-open"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        f"---\nid: {prd_unit}\ntype: prd\nabsorbs: {gap_unit}\n---\n# PRD\n",
    )
    gap_body = compose_issue_body(
        project_key,
        "gap",
        gap_unit,
        f"---\nid: {gap_unit}\ntype: gap\nstatus: open\n---\n# gap\n",
    )
    prd_rec = store.create(
        title="prd",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    gap_rec = store.create(
        title="gap",
        body=gap_body,
        labels=["sw:gap", "sw:gap-open", f"sw:unit:{gap_unit}"],
        project_key=project_key,
        artifact_type="gap",
        unit_id=gap_unit,
    )
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "units": {
                    f"{project_key}:{prd_unit}": prd_rec.id,
                    f"{project_key}:{gap_unit}": gap_rec.id,
                },
            }
        ),
        encoding="utf-8",
    )

    audit = audit_closure_completeness(root, cfg, prd_unit)
    assert audit["verdict"] == "not-ready", audit
    assert audit["openRemaining"]
    assert audit.get("resumeCommand")
    assert audit.get("considered")
    assert audit.get("closed") is not None
    assert audit.get("skipped") is not None
    assert audit.get("absorbedUnits")

    proc = subprocess.run(
        [
            "python3",
            "scripts/planning_store.py",
            "audit-closure-completeness",
            "--prd-unit",
            prd_unit,
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0, proc.stdout

def test_yaml_only_frontmatter_absorbs_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R4 — YAML-only frontmatter absorbs marker is discovered (historical parse miss)."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-070-yaml-only"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_unit = "070-prd-yaml-only-absorbs"
    gap_unit = "gap-070-yaml-only-target"
    prd_body = (
        f"---\nid: {prd_unit}\ntype: prd\nabsorbs: {gap_unit}\n---\n# PRD 070\n"
    )
    gap_body = compose_issue_body(
        project_key,
        "gap",
        gap_unit,
        f"---\nid: {gap_unit}\ntype: gap\nstatus: open\n---\n# gap\n",
    )
    prd_rec = store.create(
        title="prd",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    gap_rec = store.create(
        title="gap",
        body=gap_body,
        labels=["sw:gap", "sw:gap-open", f"sw:unit:{gap_unit}"],
        project_key=project_key,
        artifact_type="gap",
        unit_id=gap_unit,
    )
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "units": {
                    f"{project_key}:{prd_unit}": prd_rec.id,
                    f"{project_key}:{gap_unit}": gap_rec.id,
                },
            }
        ),
        encoding="utf-8",
    )

    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    assert snap["verdict"] == "ok", snap
    gap_ids = [item["unitId"] for item in snap["snapshot"] if item["artifactType"] == "gap"]
    assert gap_unit in gap_ids


def test_ambiguous_duplicate_tasks_unit_resolves_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3/R4 — duplicate tasks aliases resolve to frozen+complete and collection continues."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-070-dup-tasks"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_unit = "070-prd-duplicate-tasks"
    tasks_canonical = "tasks-070-duplicate-tasks"
    tasks_alias = "tasks-070-prd-duplicate-tasks"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        f"---\nid: {prd_unit}\ntype: prd\nstatus: complete\n---\n# PRD\n",
    )
    tasks_body = compose_issue_body(
        project_key,
        "tasks",
        tasks_canonical,
        f"---\nid: {tasks_canonical}\ntype: tasks\nstatus: complete\n---\n# tasks\n",
    )
    prd_rec = store.create(
        title="prd",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    canonical_rec = store.create(
        title="tasks",
        body=tasks_body,
        labels=["sw:tasks", FROZEN_LABEL, status_label("complete"), f"sw:unit:{tasks_canonical}"],
        project_key=project_key,
        artifact_type="tasks",
        unit_id=tasks_canonical,
    )
    store.update(canonical_rec.id, state="closed")
    alias_rec = store.create(
        title="tasks-alias",
        body=tasks_body,
        labels=["sw:tasks", f"sw:unit:{tasks_alias}"],
        project_key=project_key,
        artifact_type="tasks",
        unit_id=tasks_alias,
    )
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "units": {
                    f"{project_key}:{prd_unit}": prd_rec.id,
                    f"{project_key}:{tasks_canonical}": canonical_rec.id,
                    f"{project_key}:{tasks_alias}": alias_rec.id,
                },
            }
        ),
        encoding="utf-8",
    )

    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    assert snap["verdict"] == "ok", snap
    tasks_ids = [item["unitId"] for item in snap["snapshot"] if item["artifactType"] == "tasks"]
    assert tasks_canonical in tasks_ids
    assert len(tasks_ids) == 1


def test_ambiguous_tasks_unit_fail_closed_blocker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3/R4 — unresolvable duplicate frozen tasks fail closed with named candidates."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-070-ambig-tasks"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_unit = "070-prd-ambig-tasks"
    tasks_a = "tasks-070-ambig-tasks"
    tasks_b = "tasks-070-prd-ambig-tasks"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        f"---\nid: {prd_unit}\ntype: prd\nstatus: complete\n---\n# PRD\n",
    )
    tasks_body = compose_issue_body(
        project_key,
        "tasks",
        tasks_a,
        f"---\nid: {tasks_a}\ntype: tasks\nstatus: complete\n---\n# tasks\n",
    )
    prd_rec = store.create(
        title="prd",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    rec_a = store.create(
        title="tasks-a",
        body=tasks_body,
        labels=["sw:tasks", FROZEN_LABEL, status_label("complete"), f"sw:unit:{tasks_a}"],
        project_key=project_key,
        artifact_type="tasks",
        unit_id=tasks_a,
    )
    store.update(rec_a.id, state="closed")
    rec_b = store.create(
        title="tasks-b",
        body=tasks_body,
        labels=["sw:tasks", FROZEN_LABEL, status_label("complete"), f"sw:unit:{tasks_b}"],
        project_key=project_key,
        artifact_type="tasks",
        unit_id=tasks_b,
    )
    store.update(rec_b.id, state="closed")
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "units": {
                    f"{project_key}:{prd_unit}": prd_rec.id,
                    f"{project_key}:{tasks_a}": rec_a.id,
                    f"{project_key}:{tasks_b}": rec_b.id,
                },
            }
        ),
        encoding="utf-8",
    )

    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    assert snap["verdict"] == "ok", snap
    tasks_resolution = snap.get("tasksResolution") or {}
    assert tasks_resolution.get("verdict") == "not-ready"
    assert tasks_resolution.get("error") == "ambiguous-tasks-unit"
    assert tasks_resolution.get("candidates")


def test_missing_marker_gap_not_in_expected_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R4 — gap without anchored marker is not in the expected closure set."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-070-missing-marker"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_unit = "070-prd-missing-marker"
    gap_unit = "gap-070-unanchored"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        f"---\nid: {prd_unit}\ntype: prd\nstatus: complete\n---\n# PRD\n",
    )
    gap_body = compose_issue_body(
        project_key,
        "gap",
        gap_unit,
        f"---\nid: {gap_unit}\ntype: gap\nstatus: open\n---\n# gap\n",
    )
    prd_rec = store.create(
        title="prd",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    gap_rec = store.create(
        title="gap",
        body=gap_body,
        labels=["sw:gap", "sw:gap-open", f"sw:unit:{gap_unit}"],
        project_key=project_key,
        artifact_type="gap",
        unit_id=gap_unit,
    )
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "units": {
                    f"{project_key}:{prd_unit}": prd_rec.id,
                    f"{project_key}:{gap_unit}": gap_rec.id,
                },
            }
        ),
        encoding="utf-8",
    )

    audit = audit_closure_completeness(root, cfg, prd_unit)
    assert audit["verdict"] == "ready", audit
    assert gap_unit not in (audit.get("absorbedUnits") or [])


def test_task_ref_alias_reconciliation() -> None:
    """R3 — ledger alias refs reconcile to canonical checkbox refs."""
    assert normalize_task_ref("02.01") == "2.1"
    resolution = resolve_task_ref_aliases(["2.1", "02.01", "2.1"])
    assert resolution["verdict"] == "ok"
    assert resolution["canonical"] == ["2.1"]
    reconciled = reconcile_ledger_task_refs(
        {"02.01": {"done": True}},
        {"2.1": False},
    )
    assert reconciled["verdict"] == "ok"
    assert reconciled["tasks"]["2.1"]["done"] is True


def test_validate_pin_requires_target_with_concurrent_states(tmp_path: Path) -> None:
    """R5 — validate-pin requires --target when multiple scoped deliver states exist."""
    import argparse
    import planning_materialize as pm

    root = tmp_path
    _init_repo(root)
    cursor = root / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    (cursor / "sw-deliver-state.alpha.json").write_text(
        json.dumps({"target": {"branch": "feat/alpha"}, "verdict": "running"}),
        encoding="utf-8",
    )
    (cursor / "sw-deliver-state.beta.json").write_text(
        json.dumps({"target": {"branch": "feat/beta"}, "verdict": "running"}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as exc:
        pm.cmd_validate_pin(root, argparse.Namespace(target=None))
    assert exc.value.code == 20

    with pytest.raises(SystemExit) as exc_ok:
        pm.cmd_validate_pin(root, argparse.Namespace(target="feat/alpha"))
    assert exc_ok.value.code == 0

