"""PRD 337 R11 — no-waiver cross-PRD absorb acceptance gate (PRD 339 R37/R39)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import planning_gap_capture as pgc
from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body
from planning_store import close_delivery_units
from prd339_cross_prd_gate import (
    PRD_339_R37_ACCEPTANCE_TEST,
    PRD_339_R39_ACCEPTANCE_TEST,
    prd339_absorb_acceptance_milestone,
)


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "closure-337-gate") -> dict:
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


def _seed_prd337_closeout_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, dict]:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-337-gate"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    edges = [{"rel": "absorbs", "target": gap_id} for gap_id in pgc.PRD_337_ABSORB_GAP_UNITS]
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
    return root, cfg


def test_prd339_gate_blocked_until_acceptance_tests_exist(tmp_path: Path) -> None:
    """R11 — cross-PRD gate blocks until PRD 339 R37/R39 acceptance tests are green."""
    out = prd339_absorb_acceptance_milestone(tmp_path)
    assert out["verdict"] == "blocked"
    assert out["cause"] == "prd-339-r37-r39-not-merged-green"
    blocked_tests = {item["test"] for item in out.get("blocked") or []}
    assert PRD_339_R37_ACCEPTANCE_TEST in blocked_tests
    assert PRD_339_R39_ACCEPTANCE_TEST in blocked_tests


def test_close_delivery_units_blocked_for_prd337_without_prd339_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R11 — close-delivery-units remains blocked until PRD 339 R37/R39 milestone."""
    root, cfg = _seed_prd337_closeout_repo(tmp_path, monkeypatch)
    out = close_delivery_units(root, cfg, pgc.PRD_337_UNIT_ID, dry_run=True)
    assert out["verdict"] == "not-ready", out
    assert out.get("error") == "prd339-cross-prd-gate"
    assert out.get("cause") == "prd-339-r37-r39-not-merged-green"
    assert out.get("prd339Gate", {}).get("verdict") == "blocked"
    assert out.get("resumeCommand")


def test_close_delivery_units_unblocked_when_prd339_gate_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R11 — after PRD 339 milestone, close-delivery-units audits all seventeen gaps."""
    root, cfg = _seed_prd337_closeout_repo(tmp_path, monkeypatch)
    scripts = root / "scripts" / "unit_tests" / "planning"
    scripts.mkdir(parents=True, exist_ok=True)
  # Minimal passing acceptance stubs consumed by PRD 337; owned by PRD 339 delivery.
    (scripts / "test_prd339_list_form_absorbs_projection.py").write_text(
        "def test_r37_list_form_absorbs_projection_equivalent() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    (scripts / "test_prd339_unit_id_index_self_heal.py").write_text(
        "def test_r39_unit_id_marker_reuse_refused_and_index_self_heals() -> None:\n    assert True\n",
        encoding="utf-8",
    )
    gate = prd339_absorb_acceptance_milestone(root)
    assert gate["verdict"] == "ready", gate
    out = close_delivery_units(root, cfg, pgc.PRD_337_UNIT_ID, dry_run=True)
    assert out["verdict"] == "dry-run", out
    gap_units = [
        item["unitId"]
        for item in out.get("considered") or []
        if item.get("artifactType") == "gap"
    ]
    assert len(gap_units) == 17
    for expected in pgc.PRD_337_ABSORB_GAP_UNITS:
        assert any(pgc.gap_absorb_target_match(got, expected) for got in gap_units)
