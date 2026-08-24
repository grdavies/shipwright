"""PRD 327 R15 — absorb close-out for gap-078 (Notion planning-store provider).

ZOMBIES: Zero (no absorbs → missing gap-078) · One (single gap absorbed) ·
Many (re-merge preserves prior absorb targets) · Boundaries (hybrid body /
sw-edges fence) · Exceptions (detached gap → fail) · State (idempotent second
run; store write-through only; SW_ISSUES_FIXTURE=1 hermetic).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

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


def _issue_store_cfg(project_key: str = "closure-327") -> dict:
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


def _prd_327_frontmatter(*, with_absorbs: bool = True) -> str:
    absorbs_line = (
        f"absorbs: [{pgc.GAP_078_UNIT_ID}]\n" if with_absorbs else ""
    )
    return (
        f"---\n"
        f"id: {pgc.PRD_327_UNIT_ID}\n"
        f"type: prd\n"
        f"status: complete\n"
        f"visibility: public\n"
        f"{absorbs_line}"
        f"---\n"
        f"# PRD 327\n"
    )


def _prd_327_edges(*, with_absorbs: bool = True) -> list[dict[str, str]]:
    if not with_absorbs:
        return []
    return [{"rel": "absorbs", "target": pgc.GAP_078_UNIT_ID}]


def _fixture_prd327_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    with_absorbs: bool = True,
) -> tuple[Path, dict, FixtureIssuesStore]:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "closure-327"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    gap_id = pgc.GAP_078_UNIT_ID
    prd_body = compose_issue_body(
        project_key,
        "prd",
        pgc.PRD_327_UNIT_ID,
        _prd_327_frontmatter(with_absorbs=with_absorbs),
        edges=_prd_327_edges(with_absorbs=with_absorbs),
    )
    prd_rec = store.create(
        title="PRD 327",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{pgc.PRD_327_UNIT_ID}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=pgc.PRD_327_UNIT_ID,
    )
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
            f"# Gap 078\n"
        ),
    )
    gap_rec = store.create(
        title="Gap 078",
        body=gap_body,
        labels=["sw:gap", "sw:gap-open", f"sw:unit:{gap_id}"],
        project_key=project_key,
        artifact_type="gap",
        unit_id=gap_id,
    )
    store._persist()
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "units": {
                    f"{project_key}:{pgc.PRD_327_UNIT_ID}": prd_rec.id,
                    f"{project_key}:{gap_id}": gap_rec.id,
                },
            }
        ),
        encoding="utf-8",
    )
    return root, cfg, store


def test_discover_gap_078_from_anchored_markers() -> None:
    fm = {"absorbs": f"[{pgc.GAP_078_UNIT_ID}]"}
    edges = {"edges": _prd_327_edges()}
    discovered, skipped = discover_absorbed_units_anchored(fm, edges)
    assert any(pgc.gap_absorb_target_match(item, pgc.GAP_078_UNIT_ID) for item in discovered)
    assert not skipped


def test_resolve_delivery_linked_units_discovers_gap_078(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch)
    snap = resolve_delivery_linked_units(root, cfg, pgc.PRD_327_UNIT_ID)
    assert snap["verdict"] == "ok", snap
    gap_ids = [item["unitId"] for item in snap["snapshot"] if item["artifactType"] == "gap"]
    assert any(pgc.gap_absorb_target_match(got, pgc.GAP_078_UNIT_ID) for got in gap_ids)


def test_verify_absorb_closeout_327_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch)
    out = pgc.verify_absorb_closeout_327(root, cfg)
    assert out["verdict"] == "ok", out
    assert out["discoveredCount"] == 1
    assert not out.get("missing")


def test_verify_absorb_closeout_327_fails_when_detached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch, with_absorbs=False)
    out = pgc.verify_absorb_closeout_327(root, cfg)
    assert out["verdict"] == "fail", out
    assert any(
        pgc.gap_absorb_target_match(item, pgc.GAP_078_UNIT_ID)
        for item in (out.get("missing") or [])
    )


def test_record_and_verify_absorb_linkage_327(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch, with_absorbs=False)
    record = pgc.record_absorb_linkage_327(root, dry_run=False)
    assert record["verdict"] == "ok", record
    assert record["gapUnitId"] == pgc.GAP_078_UNIT_ID
    assert record["action"] == "record-absorb-linkage-327"

    verify = pgc.verify_absorb_closeout_327(root, cfg)
    assert verify["verdict"] == "ok", verify
    assert not verify.get("missing")


def test_record_absorb_linkage_327_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch, with_absorbs=False)
    first = pgc.record_absorb_linkage_327(root, dry_run=False)
    second = pgc.record_absorb_linkage_327(root, dry_run=False)
    assert first["verdict"] == "ok", first
    assert second["verdict"] == "ok", second
    assert pgc.verify_absorb_closeout_327(root, cfg)["verdict"] == "ok"


def test_record_absorb_linkage_327_no_local_docs_prds_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch, with_absorbs=False)
    docs_prds = root / "docs" / "prds" / "327-notion-planning-store-provider"
    docs_prds.mkdir(parents=True)
    marker = docs_prds / "marker.txt"
    marker.write_text("untouched\n", encoding="utf-8")
    before = marker.read_text(encoding="utf-8")
    out = pgc.record_absorb_linkage_327(root, dry_run=False)
    assert out["verdict"] == "ok", out
    assert marker.read_text(encoding="utf-8") == before
    assert not any(docs_prds.glob("**/*.md"))


def test_audit_closure_not_ready_with_open_absorbed_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch)
    audit = audit_closure_completeness(root, cfg, pgc.PRD_327_UNIT_ID)
    assert audit["verdict"] == "not-ready"
    assert len(audit.get("openRemaining") or []) == 1


def test_record_absorb_linkage_327_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch, with_absorbs=False)
    proc = subprocess.run(
        [
            sys.executable,
            str(scripts / "planning_gap_capture.py"),
            str(root),
            "record-absorb-linkage-327",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SW_ISSUES_FIXTURE": "1"},
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "ok", payload
    assert payload["action"] == "record-absorb-linkage-327"


def test_verify_absorb_closeout_327_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _cfg, _store = _fixture_prd327_repo(tmp_path, monkeypatch)
    proc = subprocess.run(
        [
            sys.executable,
            str(scripts / "planning_gap_capture.py"),
            str(root),
            "verify-absorb-closeout-327",
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "SW_ISSUES_FIXTURE": "1"},
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "ok", payload
    assert payload["action"] == "verify-absorb-closeout-327"
