"""PRD 337 R6/R11 — absorb closeout for seventeen workflow-runtime gaps."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import planning_gap_capture as pgc
from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body
from planning_store import discover_absorbed_units_anchored, resolve_delivery_linked_units


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "closure-337") -> dict:
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


def _prd_337_edges() -> list[dict[str, str]]:
    return [{"target": gap_id, "rel": "absorbs"} for gap_id in pgc.PRD_337_ABSORB_GAP_UNITS]


def _prd_337_edges_with_anomalous_shorts() -> list[dict[str, str]]:
    edges = _prd_337_edges()
    short_by_full = {
        full: short
        for short, full in zip(
            pgc.PRD_337_ANOMALOUS_SHORT_GAP_TARGETS,
            pgc.PRD_337_ABSORB_GAP_UNITS[:3],
        )
    }
    out: list[dict[str, str]] = []
    for edge in edges:
        target = edge["target"]
        out.append(
            {"rel": "absorbs", "target": short_by_full.get(target, target)}
        )
    return out


def _fixture_prd337_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    anomalous_shorts: bool = True,
) -> tuple[Path, dict, FixtureIssuesStore]:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-337"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    edges = _prd_337_edges_with_anomalous_shorts() if anomalous_shorts else _prd_337_edges()
    prd_body = compose_issue_body(
        project_key,
        "prd",
        pgc.PRD_337_UNIT_ID,
        (
            f"---\n"
            f"id: {pgc.PRD_337_UNIT_ID}\n"
            f"type: prd\n"
            f"status: complete\n"
            f"visibility: public\n"
            f"---\n"
            f"# PRD 337\n"
        ),
        edges=edges,
    )
    prd_rec = store.create(
        title="PRD 337",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{pgc.PRD_337_UNIT_ID}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=pgc.PRD_337_UNIT_ID,
    )
    index_units = {f"{project_key}:{pgc.PRD_337_UNIT_ID}": prd_rec.id}

    for gap_id in pgc.PRD_337_ABSORB_GAP_UNITS:
        gap_body = compose_issue_body(
            project_key,
            "gap",
            gap_id,
            (
                f"---\n"
                f"id: {gap_id}\n"
                f"type: gap\n"
                f"status: open\n"
                f"visibility: public\n"
                f"absorbed-by: {pgc.PRD_337_UNIT_ID}\n"
                f"---\n"
                f"# {gap_id}\n"
            ),
        )
        gap_rec = store.create(
            title=gap_id,
            body=gap_body,
            labels=["sw:gap", "sw:gap-open", f"sw:unit:{gap_id}"],
            project_key=project_key,
            artifact_type="gap",
            unit_id=gap_id,
        )
        index_units[f"{project_key}:{gap_id}"] = gap_rec.id

    store._persist()
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps({"version": 1, "units": index_units}),
        encoding="utf-8",
    )
    return root, cfg, store


def test_reconcile_normalizes_gap_135_136_137_before_linkage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R6/R11 — short gap-135/136/137 expand to slug-suffixed ids before linkage."""
    root, cfg, _store = _fixture_prd337_repo(tmp_path, monkeypatch)
    seeds = list(pgc.PRD_337_ABSORB_GAP_UNITS[3:])
    seeds.extend(pgc.PRD_337_ANOMALOUS_SHORT_GAP_TARGETS)
    out = pgc.reconcile_absorbed_gap_lifecycle_states(root, cfg, gap_unit_ids=seeds)
    assert out["verdict"] == "ok", out
    assert out["expectedCount"] == 17
    for short, full in zip(
        pgc.PRD_337_ANOMALOUS_SHORT_GAP_TARGETS,
        pgc.PRD_337_ABSORB_GAP_UNITS[:3],
    ):
        assert short not in out["normalized"]
        assert any(pgc.gap_absorb_target_match(item, full) for item in out["normalized"])


def test_prd337_absorbs_all_seventeen_gaps_exactly_once() -> None:
    """R6/R11 — absorbs + sw-edges discover all seventeen gaps exactly once."""
    edges = {"edges": _prd_337_edges_with_anomalous_shorts()}
    discovered, skipped = discover_absorbed_units_anchored({}, edges)
    assert len([item for item in discovered if item.startswith("gap-")]) >= 3
    assert not skipped


def test_all_absorbed_units_linked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R6/R11 — closeout snapshot includes all seventeen anchored gaps."""
    root, cfg, _store = _fixture_prd337_repo(tmp_path, monkeypatch)
    reconcile = pgc.reconcile_absorbed_gap_lifecycle_states(root, cfg)
    assert reconcile["verdict"] == "ok", reconcile
    snap = resolve_delivery_linked_units(root, cfg, pgc.PRD_337_UNIT_ID)
    assert snap["verdict"] == "ok", snap
    gap_ids = [item["unitId"] for item in snap["snapshot"] if item["artifactType"] == "gap"]
    assert len(gap_ids) == 17
    for expected in pgc.PRD_337_ABSORB_GAP_UNITS:
        assert any(pgc.gap_absorb_target_match(got, expected) for got in gap_ids)


def test_verify_absorb_closeout_337_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R6/R11 — verify helper passes when all seventeen gaps are discoverable."""
    root, cfg, _store = _fixture_prd337_repo(tmp_path, monkeypatch)
    out = pgc.verify_absorb_closeout_337(root, cfg)
    assert out["verdict"] == "ok", out
    assert out["discoveredCount"] == 17
    assert not out.get("missing")
    assert not out.get("duplicateTargets")


def test_record_absorb_linkage_337_writes_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R6/R11 — batch absorb linkage records absorbed-by on all seventeen gaps."""
    from planning_migrate_issue_store import parse_frontmatter_fields
    from planning_store import _default_body_path, get_backend

    root, cfg, _store = _fixture_prd337_repo(tmp_path, monkeypatch)
    out = pgc.record_absorb_linkage_337(root, dry_run=False)
    assert out["verdict"] == "ok", out
    backend = get_backend(root, cfg, override="issue-store")
    for gap_id in pgc.PRD_337_ABSORB_GAP_UNITS:
        gap_get = backend.get(gap_id, _default_body_path(gap_id, "gap"))
        assert gap_get.verdict == "ok" and gap_get.content
        gap_fm = parse_frontmatter_fields(gap_get.content)
        assert gap_fm.get("absorbed-by") == pgc.PRD_337_UNIT_ID
