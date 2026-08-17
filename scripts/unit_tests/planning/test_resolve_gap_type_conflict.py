"""PRD 275 phase 1 — authoritative artifact-type source order + conflict fail-closed (R16)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body, type_label
from planning_store_facade import (
    PlanningIssueRefResolutionError,
    _planning_issue_artifact_type_evidence,
    _resolve_planning_issue_artifact_type,
    resolve_planning_issue_ref_to_gap,
)


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "gap-resolver-275") -> dict:
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


def test_conflicting_type_evidence_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R16 — label vs body type disagreement fails closed."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "gap-resolver-conflict"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    gap_unit = "gap-275-type-conflict"
    body = compose_issue_body(
        project_key,
        "gap",
        gap_unit,
        f"---\nid: {gap_unit}\ntype: prd\nstatus: open\n---\n# conflict body\n",
    )
    rec = store.create(
        title="conflict",
        body=body,
        labels=[type_label("gap"), f"sw:unit:{gap_unit}"],
        project_key=project_key,
        artifact_type="gap",
        unit_id=gap_unit,
    )
    rec.number = 701
    store._issues[rec.id] = rec
    store._persist()

    evidence = _planning_issue_artifact_type_evidence(rec)
    sources = {source for source, _ in evidence}
    assert "labels" in sources
    assert "frontmatter" in sources

    with pytest.raises(PlanningIssueRefResolutionError) as exc_info:
        _resolve_planning_issue_artifact_type(rec)
    assert exc_info.value.error == "artifact-type-conflict"

    with pytest.raises(PlanningIssueRefResolutionError) as exc_info:
        resolve_planning_issue_ref_to_gap(root, cfg, "planning#701")
    assert exc_info.value.error == "artifact-type-conflict"


def test_named_source_order_labels_before_frontmatter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R16 — labels win when all sources agree on gap."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "gap-resolver-order"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    gap_unit = "gap-275-order"
    body = compose_issue_body(
        project_key,
        "gap",
        gap_unit,
        f"---\nid: {gap_unit}\ntype: gap\nstatus: open\n---\n# gap\n",
    )
    rec = store.create(
        title="gap",
        body=body,
        labels=[type_label("gap"), f"sw:unit:{gap_unit}"],
        project_key=project_key,
        artifact_type="gap",
        unit_id=gap_unit,
    )
    rec.number = 702
    store._issues[rec.id] = rec
    store._persist()

    evidence = _planning_issue_artifact_type_evidence(rec)
    assert evidence[0][0] == "labels"
    assert _resolve_planning_issue_artifact_type(rec) == "gap"
    assert resolve_planning_issue_ref_to_gap(root, cfg, "702") == gap_unit
