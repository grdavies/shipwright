"""gap-309 — closeout resolves bare issue-number absorb targets to gap units."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body, type_label
from planning_store import (
    discover_absorbed_units_anchored,
    gap_has_absorb_provenance,
    resolve_delivery_linked_units,
)
from planning_store_facade import (
    PlanningIssueRefResolutionError,
    _gap_closure_evidence,
    _is_planning_issue_absorb_ref,
    _iter_numeric_absorb_refs,
)


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "numeric-absorb-closeout") -> dict:
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


def test_is_planning_issue_absorb_ref_accepts_bare_numbers() -> None:
    assert _is_planning_issue_absorb_ref("691")
    assert _is_planning_issue_absorb_ref("#691")
    assert _is_planning_issue_absorb_ref("planning#691")
    assert not _is_planning_issue_absorb_ref("gap-292-standalone-reviewer")
    assert not _is_planning_issue_absorb_ref("docs/planning/gap/gap-292-x")
    assert not _is_planning_issue_absorb_ref("")


def test_discover_anchored_ignores_numeric_targets_offline() -> None:
    """Pure anchored discovery stays offline — numerics resolved in _gap_closure_evidence."""
    fm = {"absorbs": "[691, gap-292-standalone-reviewer]"}
    edges = {
        "edges": [
            {"rel": "absorbs", "target": "697"},
            {"rel": "absorbs", "target": "gap-296-freeze-repin"},
            {"rel": "depends", "target": "gap-related-only"},
        ]
    }
    discovered, skipped = discover_absorbed_units_anchored(fm, edges)
    assert "gap-292-standalone-reviewer" in discovered
    assert "gap-296-freeze-repin" in discovered
    assert "691" not in discovered
    assert "697" not in discovered
    assert any(item["unitId"] == "gap-related-only" for item in skipped)
    assert _iter_numeric_absorb_refs(fm, edges) == ["691", "697"]


def _fixture_numeric_absorb_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict, str, str, int]:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "numeric-absorb-closeout"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    gap_unit = "gap-292-standalone-reviewer-effectiveness-and-calibratio"
    gap_issue_num = 691
    gap_body = compose_issue_body(
        project_key,
        "gap",
        gap_unit,
        (
            f"---\nid: {gap_unit}\ntype: gap\nstatus: open\n"
            f"related: planning#{gap_issue_num}\n---\n# gap\n"
        ),
    )
    gap_rec = store.create(
        title="gap",
        body=gap_body,
        labels=[type_label("gap"), "sw:gap-open", f"sw:unit:{gap_unit}"],
        project_key=project_key,
        artifact_type="gap",
        unit_id=gap_unit,
    )
    gap_rec.number = gap_issue_num
    store._issues[gap_rec.id] = gap_rec

    prd_unit = "273-prd-reviewer-effectiveness-calibration"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        (
            f"---\nid: {prd_unit}\ntype: prd\nstatus: complete\n"
            f"planningIssues: [\"{gap_issue_num}\"]\n---\n# PRD\n"
        ),
        edges=[{"rel": "absorbs", "target": str(gap_issue_num)}],
    )
    prd_rec = store.create(
        title="prd",
        body=prd_body,
        labels=[type_label("prd"), f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )

    store._persist()
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
    return root, cfg, prd_unit, gap_unit, gap_issue_num


def test_gap_closure_evidence_resolves_numeric_edge_absorbs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, _prd, gap_unit, issue_num = _fixture_numeric_absorb_repo(tmp_path, monkeypatch)
    fm = {"planningIssues": f'["{issue_num}"]'}
    edges = {"edges": [{"rel": "absorbs", "target": str(issue_num)}]}
    discovered, skipped = _gap_closure_evidence(fm, edges, "273", root, cfg)
    assert gap_unit in discovered
    assert not any(item.get("ref") == str(issue_num) for item in skipped)


def test_gap_has_absorb_provenance_via_numeric_edge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, prd_unit, gap_unit, issue_num = _fixture_numeric_absorb_repo(tmp_path, monkeypatch)
    fm = {"planningIssues": f'["{issue_num}"]'}
    edges = {"edges": [{"rel": "absorbs", "target": str(issue_num)}]}
    assert gap_has_absorb_provenance(
        root, cfg, gap_unit, prd_unit, fm, prd_num="273", edges=edges
    )


def test_resolve_delivery_linked_units_includes_numeric_absorb_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: PRD/tasks-only snapshot must not drop numeric sw-edges absorbs."""
    root, cfg, prd_unit, gap_unit, _issue_num = _fixture_numeric_absorb_repo(
        tmp_path, monkeypatch
    )
    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    assert snap["verdict"] == "ok", snap
    gap_ids = [item["unitId"] for item in snap["snapshot"] if item["artifactType"] == "gap"]
    assert gap_unit in gap_ids
    assert not any(
        item.get("reason") == "planning-issue-no-provenance" for item in (snap.get("skipped") or [])
    )


def test_numeric_absorb_unresolved_returns_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0-match numeric absorb → typed not-ready (PRD 278 R6/D5)."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "numeric-absorb-closeout"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_unit = "278-prd-missing-gap"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        f"---\nid: {prd_unit}\ntype: prd\nstatus: complete\n---\n# PRD\n",
        edges=[{"rel": "absorbs", "target": "999"}],
    )
    prd_rec = store.create(
        title="prd",
        body=prd_body,
        labels=[type_label("prd"), f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    store._persist()
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps({"version": 1, "units": {f"{project_key}:{prd_unit}": prd_rec.id}}),
        encoding="utf-8",
    )
    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    assert snap["verdict"] == "not-ready", snap
    assert snap["error"] == "absorb-gap-unresolved"
    assert snap.get("planningIssueRef") == "999"


def test_numeric_absorb_ambiguous_returns_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N>1 eligible open gaps for one numeric absorb → typed not-ready."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "numeric-absorb-closeout"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    issue_num = 777
    gap_ids = ("gap-777-alpha", "gap-777-beta")
    index_units: dict[str, str] = {}
    for gap_unit in gap_ids:
        gap_body = compose_issue_body(
            project_key,
            "gap",
            gap_unit,
            (
                f"---\nid: {gap_unit}\ntype: gap\nstatus: open\n"
                f"related: planning#{issue_num}\n---\n# gap\n"
            ),
        )
        gap_rec = store.create(
            title=gap_unit,
            body=gap_body,
            labels=[type_label("gap"), "sw:gap-open", f"sw:unit:{gap_unit}"],
            project_key=project_key,
            artifact_type="gap",
            unit_id=gap_unit,
        )
        index_units[f"{project_key}:{gap_unit}"] = gap_rec.id

    prd_unit = "278-prd-ambiguous"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        f"---\nid: {prd_unit}\ntype: prd\nstatus: complete\n---\n# PRD\n",
        edges=[{"rel": "absorbs", "target": str(issue_num)}],
    )
    prd_rec = store.create(
        title="prd",
        body=prd_body,
        labels=[type_label("prd"), f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    index_units[f"{project_key}:{prd_unit}"] = prd_rec.id
    store._persist()
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps({"version": 1, "units": index_units}),
        encoding="utf-8",
    )
    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    assert snap["verdict"] == "not-ready", snap
    assert snap["error"] == "absorb-gap-ambiguous"
    assert set(snap.get("candidates") or []) == set(gap_ids)


def test_numeric_absorb_provider_fault_returns_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Provider/API fault during numeric resolve → not-ready (PRD 278 R7)."""
    from issues_lib import IssueCapabilityError, IssuesClient

    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "numeric-absorb-closeout"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_unit = "278-prd-provider-fault"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        f"---\nid: {prd_unit}\ntype: prd\nstatus: complete\n---\n# PRD\n",
        edges=[{"rel": "absorbs", "target": "888"}],
    )
    prd_rec = store.create(
        title="prd",
        body=prd_body,
        labels=[type_label("prd"), f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    store._persist()
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps({"version": 1, "units": {f"{project_key}:{prd_unit}": prd_rec.id}}),
        encoding="utf-8",
    )

    original_issue_get = IssuesClient.issue_get

    def _raising_issue_get(self, issue_id: str):
        if issue_id == "888":
            raise IssueCapabilityError("auth-scope-denied")
        return original_issue_get(self, issue_id)

    monkeypatch.setattr(IssuesClient, "issue_get", _raising_issue_get)

    with pytest.raises(PlanningIssueRefResolutionError) as excinfo:
        _gap_closure_evidence({}, {"edges": [{"rel": "absorbs", "target": "888"}]}, "278", root, cfg)
    assert excinfo.value.error == "issue-capability-error"

    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    assert snap["verdict"] == "not-ready", snap
    assert snap["error"] == "issue-capability-error"
