"""Short gap-NNN sw-edges absorbs must expand to slug-suffixed unit ids (closeout)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body, type_label
from planning_store import resolve_delivery_linked_units
from planning_store_facade import (
    PlanningIssueRefResolutionError,
    _canonicalize_short_gap_absorb_targets,
    _gap_closure_evidence,
    _is_short_gap_number_target,
)


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "short-gap-absorb") -> dict:
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


def test_is_short_gap_number_target() -> None:
    assert _is_short_gap_number_target("gap-323")
    assert _is_short_gap_number_target("gap-1")
    assert not _is_short_gap_number_target("gap-323-external-issue-intake")
    assert not _is_short_gap_number_target("323")
    assert not _is_short_gap_number_target("")


def _fixture_short_gap_absorb_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict, str, str]:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "short-gap-absorb"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    gap_unit = "gap-323-external-issue-intake-and-triage-lifecycle"
    gap_body = compose_issue_body(
        project_key,
        "gap",
        gap_unit,
        f"---\nid: {gap_unit}\ntype: gap\nstatus: open\n---\n# gap\n",
    )
    gap_rec = store.create(
        title="External issue intake",
        body=gap_body,
        labels=[type_label("gap"), "sw:gap-open", f"sw:unit:{gap_unit}"],
        project_key=project_key,
        artifact_type="gap",
        unit_id=gap_unit,
    )
    gap_rec.number = 759
    store._issues[gap_rec.id] = gap_rec

    prd_unit = "280-prd-workflow-extensions"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        f"---\nid: {prd_unit}\ntype: prd\nstatus: complete\n---\n# PRD\n",
        edges=[{"rel": "absorbs", "target": "gap-323"}],
    )
    prd_rec = store.create(
        title="PRD workflow extensions",
        body=prd_body,
        labels=[type_label("prd"), f"sw:unit:{prd_unit}", "sw:absorbs:gap-323"],
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
    return root, cfg, prd_unit, gap_unit


def test_gap_closure_evidence_expands_short_gap_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, _prd, gap_unit = _fixture_short_gap_absorb_repo(tmp_path, monkeypatch)
    edges = {"edges": [{"rel": "absorbs", "target": "gap-323"}]}
    discovered, skipped = _gap_closure_evidence({}, edges, "280", root, cfg)
    assert gap_unit in discovered
    assert "gap-323" not in discovered
    assert not any(item.get("unitId") == "gap-323" for item in skipped)


def test_resolve_delivery_linked_units_includes_short_gap_absorb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: short sw-edges gap-NNN must not silently drop from snapshot."""
    root, cfg, prd_unit, gap_unit = _fixture_short_gap_absorb_repo(tmp_path, monkeypatch)
    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    assert snap["verdict"] == "ok", snap
    gap_ids = [item["unitId"] for item in snap["snapshot"] if item["artifactType"] == "gap"]
    assert gap_unit in gap_ids
    assert "gap-323" not in gap_ids


def test_short_gap_unresolved_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "short-gap-absorb"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_unit = "280-prd-missing-short-gap"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        f"---\nid: {prd_unit}\ntype: prd\nstatus: complete\n---\n# PRD\n",
        edges=[{"rel": "absorbs", "target": "gap-999"}],
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
                "units": {f"{project_key}:{prd_unit}": prd_rec.id},
            }
        ),
        encoding="utf-8",
    )

    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    assert snap["verdict"] == "not-ready", snap
    assert snap.get("error") == "gap-unit-unresolved"
    assert snap.get("planningIssueRef") == "gap-999"


def test_short_gap_ambiguous_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "short-gap-absorb"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    gap_a = "gap-316-architecture-health-refactoring-radar"
    gap_b = "gap-316-architecture-health-alt"
    index: dict[str, str] = {}
    for gap_unit, num in ((gap_a, 752), (gap_b, 753)):
        body = compose_issue_body(
            project_key,
            "gap",
            gap_unit,
            f"---\nid: {gap_unit}\ntype: gap\nstatus: open\n---\n# gap\n",
        )
        rec = store.create(
            title=gap_unit,
            body=body,
            labels=[type_label("gap"), "sw:gap-open", f"sw:unit:{gap_unit}"],
            project_key=project_key,
            artifact_type="gap",
            unit_id=gap_unit,
        )
        rec.number = num
        store._issues[rec.id] = rec
        index[f"{project_key}:{gap_unit}"] = rec.id

    store._persist()
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps({"version": 1, "units": index}),
        encoding="utf-8",
    )
    with pytest.raises(PlanningIssueRefResolutionError) as excinfo:
        _canonicalize_short_gap_absorb_targets(root, cfg, {"gap-316"}, fail_closed=True)
    assert excinfo.value.error == "gap-unit-ambiguous"
    assert set(excinfo.value.detail.get("candidates") or []) == {gap_a, gap_b}
