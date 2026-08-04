"""PRD 093 phase 3 — put() sw-edges preservation on metadata-only round trips (R3–R6)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from planning_canonical import build_edges_block, parse_edges_block, reconcile_edges
from planning_gap_capture import _merge_gap_absorb_schedule
from planning_store import IssueStoreBackend, _default_body_path


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "edge-preservation-093") -> dict:
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
        f"---\nid: {gap_unit}\ntype: gap\nstatus: open\nvisibility: public\n---\n# Gap with edges\n"
        + build_edges_block(edge_list, native_links)
    )
    put = backend.put(gap_unit, gap_path, body_md, content_class="canonical")
    assert put.verdict == "ok", put
    return gap_path, native_links


def test_put_preserves_edges_on_metadata_only_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3/R5 — metadata-only put keeps stored sw-edges and native projection."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "edge-preservation-093"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")

    parent_unit = "gap-parent-edge-preservation"
    parent_path = _default_body_path(parent_unit, "gap")
    gap_unit = "gap-child-edge-preservation"
    prd_unit = "093-prd-freeze-etag-retry-and-absorb-edge-preservation"

    backend = IssueStoreBackend(root, cfg)
    parent_put = backend.put(
        parent_unit,
        parent_path,
        f"---\nid: {parent_unit}\ntype: gap\nstatus: open\nvisibility: public\n---\n# parent\n",
    )
    assert parent_put.verdict == "ok"
    parent_get = backend.get(parent_unit, parent_path)
    assert parent_get.verdict == "ok"
    from issues_lib import FixtureIssuesStore

    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    parent_rec = store.find_by_unit(project_key, parent_unit)
    assert parent_rec is not None
    parent_issue_id = parent_rec.id

    gap_path, original_native = _fixture_gap_with_edges(
        backend,
        project_key=project_key,
        gap_unit=gap_unit,
        parent_unit=parent_unit,
        parent_issue_id=parent_issue_id,
    )

    before = backend.get(gap_unit, gap_path)
    assert before.verdict == "ok" and before.content
    merged, changed = _merge_gap_absorb_schedule(
        before.content,
        prd_unit_id=prd_unit,
        prd_number="093",
        planning_issue="planning#501",
    )
    assert changed
    assert parse_edges_block(merged) is None

    put = backend.put(gap_unit, gap_path, merged)
    assert put.verdict == "ok", put

    after = backend.get(gap_unit, gap_path)
    assert after.verdict == "ok" and after.content

    record = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json").find_by_unit(
        project_key, gap_unit
    )
    assert record is not None
    body_edges = parse_edges_block(record.body)
    assert body_edges is not None
    assert body_edges.get("edges")
    assert body_edges.get("native") == original_native
    reconciled = reconcile_edges(body_edges, record.native_links)
    assert reconciled.get("native") == original_native


def test_put_prefers_caller_declared_edges_over_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R4 — caller sw-edges block wins over previously stored edges."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "edge-preservation-093-r4"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")

    old_parent = "gap-old-parent"
    new_parent = "gap-new-parent"
    gap_unit = "gap-caller-edges"
    backend = IssueStoreBackend(root, cfg)

    for uid in (old_parent, new_parent):
        path = _default_body_path(uid, "gap")
        assert backend.put(uid, path, f"---\nid: {uid}\ntype: gap\nvisibility: public\n---\n# {uid}\n").verdict == "ok"

    from issues_lib import FixtureIssuesStore

    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    old_rec = store.find_by_unit(project_key, old_parent)
    new_rec = store.find_by_unit(project_key, new_parent)
    assert old_rec and new_rec

    gap_path, _ = _fixture_gap_with_edges(
        backend,
        project_key=project_key,
        gap_unit=gap_unit,
        parent_unit=old_parent,
        parent_issue_id=old_rec.id,
    )

    new_edges = [{"rel": "depends", "target": new_parent}]
    new_native = [{"type": "depends-on", "target": new_rec.id}]
    caller_body = (
        f"---\nid: {gap_unit}\ntype: gap\nstatus: scheduled\nvisibility: public\n---\n# updated\n"
        + build_edges_block(new_edges, new_native)
    )
    put = backend.put(gap_unit, gap_path, caller_body)
    assert put.verdict == "ok", put

    after = backend.get(gap_unit, gap_path)
    assert after.verdict == "ok" and after.content

    gap_rec = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json").find_by_unit(
        project_key, gap_unit
    )
    assert gap_rec is not None
    body_edges = parse_edges_block(gap_rec.body)
    assert body_edges is not None
    assert body_edges.get("edges") == new_edges
    assert body_edges.get("native") == new_native
    reconciled = reconcile_edges(body_edges, gap_rec.native_links)
    assert reconciled.get("native") == new_native
