"""PRD 275 phase 1 — closeout discovery skips non-gap without freeze-check (R6/R7)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import planning_gap_capture as pgc
from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body, FROZEN_LABEL, type_label
from planning_store import IssueStoreBackend, resolve_delivery_linked_units


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "gap-resolver-closeout") -> dict:
    return {
        "version": 1,
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": project_key,
            }
        },
        "host": {"provider": "github"},
    }


def test_closeout_skips_nongap_without_freeze_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R6 — non-gap planningIssues refs skip discovery without freeze failure."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "gap-resolver-closeout"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    tasks_unit = "tasks-275-closeout-hygiene"
    tasks_body = compose_issue_body(
        project_key,
        "tasks",
        tasks_unit,
        f"---\nid: {tasks_unit}\ntype: tasks\nstatus: frozen\n---\n# tasks\n",
    )
    tasks_rec = store.create(
        title="tasks",
        body=tasks_body,
        labels=[type_label("tasks"), FROZEN_LABEL, f"sw:unit:{tasks_unit}"],
        project_key=project_key,
        artifact_type="tasks",
        unit_id=tasks_unit,
    )
    tasks_rec.number = 705
    store._issues[tasks_rec.id] = tasks_rec

    prd_unit = "275-prd-closeout-hygiene"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        (
            f"---\nid: {prd_unit}\ntype: prd\nstatus: complete\n"
            f"planningIssues: planning#705\n---\n# PRD\n"
        ),
    )
    prd_rec = store.create(
        title="prd",
        body=prd_body,
        labels=[type_label("prd"), f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "units": {
                    f"{project_key}:{prd_unit}": prd_rec.id,
                    f"{project_key}:{tasks_unit}": tasks_rec.id,
                },
            }
        ),
        encoding="utf-8",
    )

    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    assert snap["verdict"] == "ok", snap
    gap_ids = [item["unitId"] for item in snap["snapshot"] if item["artifactType"] == "gap"]
    assert tasks_unit not in gap_ids
    assert any(
        item.get("reason") == "planning-issue-nongap" and item.get("ref") == "planning#705"
        for item in snap.get("skipped", [])
    )

    absorb = pgc.record_absorb_linkage(
        root,
        prd_unit_id=prd_unit,
        prd_number="275",
        planning_issues=["planning#705"],
        dry_run=True,
    )
    assert absorb["verdict"] == "skipped", absorb
    assert absorb.get("reason") == "no-absorb-targets"


def test_planning_issues_prd_self_ref_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R7 — PRD self-ref in planningIssues is skipped (no gap discovery)."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "gap-resolver-self-ref"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_unit = "275-prd-self-ref"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        (
            f"---\nid: {prd_unit}\ntype: prd\nstatus: complete\n"
            f"planningIssues: planning#706\n---\n# PRD\n"
        ),
    )
    prd_rec = store.create(
        title="prd",
        body=prd_body,
        labels=[type_label("prd"), f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    prd_rec.number = 706
    store._issues[prd_rec.id] = prd_rec
    store._persist()
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps({"version": 1, "units": {f"{project_key}:{prd_unit}": prd_rec.id}}),
        encoding="utf-8",
    )

    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    assert snap["verdict"] == "ok", snap
    gap_ids = [item["unitId"] for item in snap["snapshot"] if item["artifactType"] == "gap"]
    assert prd_unit not in gap_ids
    assert any(item.get("reason") == "planning-issue-nongap" for item in snap.get("skipped", []))

    backend = IssueStoreBackend(root, cfg)
    prd_get = backend.get(prd_unit, f"docs/prds/275-closeout-hygiene/{prd_unit}.md")
    assert prd_get.verdict == "ok"
