"""Regression tests for gap-112 post-deliver closure completeness (PRD 060 R4–R7)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from issues_lib import FixtureIssuesStore
from planning_progress import phase_done_label, sync_phase_done
from planning_store import (
    _gap_closure_evidence,
    _prd_unit_id_alias_candidates,
    close_delivery_units,
    close_done_phase_sub_issues,
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
