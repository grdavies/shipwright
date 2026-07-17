"""PRD 072 phase 10 — absorb close-out + packaging parity (R10)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import planning_gap_capture as pgc
from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body
from planning_store import (
    audit_closure_completeness,
    discover_absorbed_units_anchored,
    resolve_delivery_linked_units,
)


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "closure-072") -> dict:
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


def _prd_072_frontmatter() -> str:
    absorbs = ", ".join(pgc.PRD_072_ABSORB_GAP_UNITS)
    issues = ", ".join(str(n) for n in pgc.PRD_072_PLANNING_ISSUE_NUMBERS)
    return (
        f"---\n"
        f"id: {pgc.PRD_072_UNIT_ID}\n"
        f"type: prd\n"
        f"status: complete\n"
        f"visibility: public\n"
        f"planningIssues: [{issues}]\n"
        f"absorbs: [{absorbs}]\n"
        f"---\n"
        f"# PRD 072\n"
    )


def _prd_072_edges() -> list[dict[str, str]]:
    return [{"target": gap_id} for gap_id in pgc.PRD_072_ABSORB_GAP_UNITS]


def _fixture_prd072_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict, FixtureIssuesStore]:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-072"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_body = compose_issue_body(
        project_key,
        "prd",
        pgc.PRD_072_UNIT_ID,
        _prd_072_frontmatter(),
        edges=_prd_072_edges(),
    )
    prd_rec = store.create(
        title="PRD 072",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{pgc.PRD_072_UNIT_ID}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=pgc.PRD_072_UNIT_ID,
    )
    index_units = {f"{project_key}:{pgc.PRD_072_UNIT_ID}": prd_rec.id}

    for gap_id, issue_num in zip(pgc.PRD_072_ABSORB_GAP_UNITS, pgc.PRD_072_PLANNING_ISSUE_NUMBERS):
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
                f"related: planning#{issue_num}\n"
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
        gap_rec.number = issue_num
        store._issues[gap_rec.id] = gap_rec
        index_units[f"{project_key}:{gap_id}"] = gap_rec.id

    store._persist()
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps({"version": 1, "units": index_units}),
        encoding="utf-8",
    )
    return root, cfg, store


def test_discover_all_nine_gaps_from_anchored_markers() -> None:
    """R10 — absorbs + sw-edges discover all nine delivery-grade gaps."""
    fm = {
        "absorbs": "[" + ", ".join(pgc.PRD_072_ABSORB_GAP_UNITS) + "]",
        "planningIssues": "[" + ", ".join(str(n) for n in pgc.PRD_072_PLANNING_ISSUE_NUMBERS) + "]",
    }
    edges = {"edges": _prd_072_edges()}
    discovered, skipped = discover_absorbed_units_anchored(fm, edges)
    assert len(discovered) == 9, (discovered, skipped)
    for gap_id in pgc.PRD_072_ABSORB_GAP_UNITS:
        assert any(pgc.gap_absorb_target_match(item, gap_id) for item in discovered)


def test_resolve_delivery_linked_units_discovers_nine_gaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R10 — close-out snapshot includes all nine anchored gaps."""
    root, cfg, _store = _fixture_prd072_repo(tmp_path, monkeypatch)
    snap = resolve_delivery_linked_units(root, cfg, pgc.PRD_072_UNIT_ID)
    assert snap["verdict"] == "ok", snap
    gap_ids = [item["unitId"] for item in snap["snapshot"] if item["artifactType"] == "gap"]
    assert len(gap_ids) == 9
    for expected in pgc.PRD_072_ABSORB_GAP_UNITS:
        assert any(pgc.gap_absorb_target_match(got, expected) for got in gap_ids)


def test_verify_absorb_closeout_072_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R10 — verify helper passes when all nine gaps are discoverable."""
    root, cfg, _store = _fixture_prd072_repo(tmp_path, monkeypatch)
    out = pgc.verify_absorb_closeout_072(root, cfg)
    assert out["verdict"] == "ok", out
    assert out["discoveredCount"] == 9
    assert not out.get("missing")


def test_verify_absorb_closeout_072_fails_on_silent_leave_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R10 — missing anchored gap is reported; silent leave-open forbidden."""
    root, cfg, store = _fixture_prd072_repo(tmp_path, monkeypatch)
    prd_rec = store.find_by_unit("closure-072", pgc.PRD_072_UNIT_ID)
    assert prd_rec is not None
    pruned = prd_rec.body.replace(pgc.PRD_072_ABSORB_GAP_UNITS[0], "gap-999-pruned-away")
    store.update(prd_rec.id, body=pruned)
    out = pgc.verify_absorb_closeout_072(root, cfg)
    assert out["verdict"] == "fail", out
    assert out.get("missing")


def test_audit_closure_not_ready_with_open_absorbed_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R10 — open absorbed gap blocks close-out audit (no silent leave-open)."""
    root, cfg, _store = _fixture_prd072_repo(tmp_path, monkeypatch)
    audit = audit_closure_completeness(root, cfg, pgc.PRD_072_UNIT_ID)
    assert audit["verdict"] == "not-ready"
    assert len(audit.get("openRemaining") or []) == 9


def test_record_absorb_linkage_072_writes_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R10 — batch absorb linkage records absorbed-by on all nine gaps."""
    from planning_migrate_issue_store import parse_frontmatter_fields
    from planning_store import _default_body_path, get_backend

    root, cfg, _store = _fixture_prd072_repo(tmp_path, monkeypatch)
    out = pgc.record_absorb_linkage_072(root, dry_run=False)
    assert out["verdict"] == "ok", out
    backend = get_backend(root, cfg, override="issue-store")
    for gap_id in pgc.PRD_072_ABSORB_GAP_UNITS:
        gap_get = backend.get(gap_id, _default_body_path(gap_id, "gap"))
        assert gap_get.verdict == "ok" and gap_get.content
        gap_fm = parse_frontmatter_fields(gap_get.content)
        assert gap_fm.get("absorbed-by") == pgc.PRD_072_UNIT_ID
