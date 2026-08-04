"""PRD 093 phase 4 — record_absorb_linkage end-to-end edge preservation (R5)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from issues_lib import FixtureIssuesStore
from planning_canonical import build_edges_block, parse_edges_block, reconcile_edges
import planning_gap_capture as pgc
from planning_store import IssueStoreBackend, _default_body_path


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "absorb-linkage-093") -> dict:
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


def _fixture_gap_with_edges(
    backend: IssueStoreBackend,
    *,
    project_key: str,
    gap_unit: str,
    parent_unit: str,
    parent_issue_id: str,
    issue_number: int,
) -> tuple[str, list[dict[str, object]]]:
    gap_path = _default_body_path(gap_unit, "gap")
    edge_list = [
        {"rel": "depends", "target": parent_unit},
        {"rel": "sub-issue-of", "target": parent_unit},
    ]
    native_links = [
        {"type": "depends-on", "target": parent_issue_id},
        {"type": "sub-issue-of", "target": parent_issue_id},
    ]
    body_md = (
        f"---\nid: {gap_unit}\ntype: gap\nstatus: open\nvisibility: public\n---\n# Gap {gap_unit}\n"
        + build_edges_block(edge_list, native_links)
    )
    put = backend.put(gap_unit, gap_path, body_md, content_class="canonical")
    assert put.verdict == "ok", put
    store = FixtureIssuesStore(backend.root / ".cursor/hooks/state/issue-store-fixture.json")
    rec = store.find_by_unit(project_key, gap_unit)
    assert rec is not None
    rec.number = issue_number
    store._issues[rec.id] = rec
    store._persist()
    return gap_path, native_links


def test_record_absorb_linkage_preserves_edges_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R5 — absorb-linkage round-trip preserves sw-edges on every affected gap."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "absorb-linkage-093"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")

    parent_unit = "gap-parent-absorb-093"
    gap_units = ["gap-child-a-absorb-093", "gap-child-b-absorb-093"]
    prd_unit = "093-prd-freeze-etag-retry-and-absorb-edge-preservation"
    original_native: dict[str, list[dict[str, object]]] = {}

    backend = IssueStoreBackend(root, cfg)
    parent_path = _default_body_path(parent_unit, "gap")
    parent_put = backend.put(
        parent_unit,
        parent_path,
        f"---\nid: {parent_unit}\ntype: gap\nstatus: open\nvisibility: public\n---\n# parent\n",
    )
    assert parent_put.verdict == "ok"

    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    parent_rec = store.find_by_unit(project_key, parent_unit)
    assert parent_rec is not None
    parent_issue_id = parent_rec.id

    for idx, gap_unit in enumerate(gap_units, start=1):
        _, native = _fixture_gap_with_edges(
            backend,
            project_key=project_key,
            gap_unit=gap_unit,
            parent_unit=parent_unit,
            parent_issue_id=parent_issue_id,
            issue_number=500 + idx,
        )
        original_native[gap_unit] = native

    prd_path = _default_body_path(prd_unit, "prd")
    prd_body = (
        f"---\nid: {prd_unit}\ntype: prd\nstatus: draft\nfrozen: true\nvisibility: public\n---\n"
        f"# PRD 093 absorb linkage e2e\n"
    )
    assert backend.put(prd_unit, prd_path, prd_body).verdict == "ok"

    out = pgc.record_absorb_linkage(
        root,
        prd_unit_id=prd_unit,
        prd_number="093",
        gap_unit_ids=gap_units,
        planning_issue="planning#501",
        dry_run=False,
    )
    assert out["verdict"] == "ok", out

    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    for gap_unit in gap_units:
        gap_path = _default_body_path(gap_unit, "gap")
        fetched = backend.get(gap_unit, gap_path)
        assert fetched.verdict == "ok" and fetched.content

        record = store.find_by_unit(project_key, gap_unit)
        assert record is not None
        body_edges = parse_edges_block(record.body)
        assert body_edges is not None
        assert body_edges.get("edges")
        expected_native = original_native[gap_unit]
        assert body_edges.get("native") == expected_native
        reconciled = reconcile_edges(body_edges, record.native_links)
        assert reconciled.get("native") == expected_native
