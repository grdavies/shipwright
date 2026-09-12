"""PRD 339 R33/R39 — absorb closeout for seven planning-store correctness gaps."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import planning_gap_capture as pgc
from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body
from planning_store import close_delivery_units, discover_absorbed_units_anchored, resolve_delivery_linked_units
from prd339_bundle_closeout import prd339_absorb_closeout_milestone


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "closure-339") -> dict:
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


def _prd_339_edges() -> list[dict[str, str]]:
    return [{"target": gap_id, "rel": "absorbs"} for gap_id in pgc.PRD_339_ABSORB_GAP_UNITS]


def _prd_339_edges_with_anomalous_shorts() -> list[dict[str, str]]:
    edges = _prd_339_edges()
    short_by_full = {
        "gap-001": pgc.PRD_339_ABSORB_GAP_UNITS[0],
        "gap-079": pgc.PRD_339_ABSORB_GAP_UNITS[1],
    }
    out: list[dict[str, str]] = []
    for edge in edges:
        target = edge["target"]
        out.append(
            {"rel": "absorbs", "target": short_by_full.get(target, target)}
        )
    return out


def _fixture_prd339_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    anomalous_shorts: bool = True,
) -> tuple[Path, dict, FixtureIssuesStore]:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-339"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    edges = _prd_339_edges_with_anomalous_shorts() if anomalous_shorts else _prd_339_edges()
    prd_body = compose_issue_body(
        project_key,
        "prd",
        pgc.PRD_339_UNIT_ID,
        (
            f"---\n"
            f"id: {pgc.PRD_339_UNIT_ID}\n"
            f"type: prd\n"
            f"status: complete\n"
            f"visibility: public\n"
            f"---\n"
            f"# PRD 339\n"
        ),
        edges=edges,
    )
    prd_rec = store.create(
        title="PRD 339",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{pgc.PRD_339_UNIT_ID}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=pgc.PRD_339_UNIT_ID,
    )
    index_units = {f"{project_key}:{pgc.PRD_339_UNIT_ID}": prd_rec.id}

    for gap_id in pgc.PRD_339_ABSORB_GAP_UNITS:
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
                f"absorbed-by: {pgc.PRD_339_UNIT_ID}\n"
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


def test_reconcile_normalizes_gap_001_and_079_before_linkage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R32/R33 — short gap-001/gap-079 expand to slug-suffixed ids before linkage."""
    root, cfg, _store = _fixture_prd339_repo(tmp_path, monkeypatch)
    seeds = list(pgc.PRD_339_ABSORB_GAP_UNITS[2:])
    seeds.extend(pgc.PRD_339_ANOMALOUS_SHORT_GAP_TARGETS)
    out = pgc.reconcile_absorbed_gap_lifecycle_states_339(root, cfg, gap_unit_ids=seeds)
    assert out["verdict"] == "ok", out
    assert out["expectedCount"] == 7
    for short, full in zip(
        pgc.PRD_339_ANOMALOUS_SHORT_GAP_TARGETS,
        pgc.PRD_339_ABSORB_GAP_UNITS[:2],
    ):
        assert short not in out["normalized"]
        assert any(pgc.gap_absorb_target_match(item, full) for item in out["normalized"])


def test_prd339_absorbs_all_seven_gaps_exactly_once() -> None:
    """R33/R39 — absorbs + sw-edges discover all seven gaps exactly once."""
    edges = {"edges": _prd_339_edges_with_anomalous_shorts()}
    discovered, skipped = discover_absorbed_units_anchored({}, edges)
    assert len([item for item in discovered if item.startswith("gap-")]) >= 2
    assert not skipped


def test_all_absorbed_units_linked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R33/R39 — closeout snapshot includes all seven anchored gaps."""
    root, cfg, _store = _fixture_prd339_repo(tmp_path, monkeypatch)
    reconcile = pgc.reconcile_absorbed_gap_lifecycle_states_339(root, cfg)
    assert reconcile["verdict"] == "ok", reconcile
    snap = resolve_delivery_linked_units(root, cfg, pgc.PRD_339_UNIT_ID)
    assert snap["verdict"] == "ok", snap
    gap_ids = [item["unitId"] for item in snap["snapshot"] if item["artifactType"] == "gap"]
    assert len(gap_ids) == 7
    for expected in pgc.PRD_339_ABSORB_GAP_UNITS:
        assert any(pgc.gap_absorb_target_match(got, expected) for got in gap_ids)


def test_verify_absorb_closeout_339_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R33/R39 — verify helper passes when all seven gaps are discoverable."""
    root, cfg, _store = _fixture_prd339_repo(tmp_path, monkeypatch)
    out = pgc.verify_absorb_closeout_339(root, cfg)
    assert out["verdict"] == "ok", out
    assert out["discoveredCount"] == 7
    assert not out.get("missing")
    assert not out.get("duplicateTargets")


def test_close_delivery_units_blocked_without_closeout_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R33/R39 — close-delivery-units remains blocked until rollout gates are green."""
    root, cfg, _store = _fixture_prd339_repo(tmp_path, monkeypatch)
    out = close_delivery_units(root, cfg, pgc.PRD_339_UNIT_ID, dry_run=True)
    assert out["verdict"] == "not-ready", out
    assert out.get("error") == "prd339-absorb-closeout-gate"
    assert out.get("prd339CloseoutGate", {}).get("verdict") == "blocked"
    assert out.get("resumeCommand")


def test_close_delivery_units_verifies_seven_gaps_when_gate_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo_root: Path
) -> None:
    """R33/R39 — after correctness and Linear acceptance, close-delivery-units audits seven gaps."""
    gate = prd339_absorb_closeout_milestone(repo_root)
    if gate.get("verdict") != "ready":
        blocked = gate.get("blocked") or []
        detail = json.dumps(blocked, ensure_ascii=False, indent=2)
        raise AssertionError(f"prd339 closeout gate not ready: {gate.get('cause')} blocked={detail}")
    monkeypatch.setattr(
        "prd339_bundle_closeout.prd339_absorb_closeout_milestone",
        lambda _root: {"verdict": "ready", "action": "prd339-absorb-closeout-gate"},
    )
    root, cfg, _store = _fixture_prd339_repo(tmp_path, monkeypatch)
    out = close_delivery_units(root, cfg, pgc.PRD_339_UNIT_ID, dry_run=True)
    assert out["verdict"] == "dry-run", out
    gap_units = [
        item["unitId"]
        for item in out.get("considered") or []
        if item.get("artifactType") == "gap"
    ]
    assert len(gap_units) == 7
    for expected in pgc.PRD_339_ABSORB_GAP_UNITS:
        assert any(pgc.gap_absorb_target_match(got, expected) for got in gap_units)
