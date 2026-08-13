"""PRD 094 phase 4 / R12 — absorbs regression fixtures (put→get, semantic no-op, edges)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from issues_lib import FixtureIssuesStore
from planning_canonical import (
    build_edges_block,
    parse_absorbs_from_canonical_content,
    parse_edges_block,
    reconcile_edges,
)
from planning_gap_capture import _merge_prd_absorbs_frontmatter
from planning_store import IssueStoreBackend, _default_body_path


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "absorbs-r12-094") -> dict:
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


def _fixture_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_key: str = "absorbs-r12-094"
) -> IssueStoreBackend:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    _init_repo(tmp_path)
    cfg = _issue_store_cfg(project_key)
    (tmp_path / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return IssueStoreBackend(tmp_path, cfg)


def _assert_no_edge_divergence(
    backend: IssueStoreBackend,
    *,
    project_key: str,
    unit_id: str,
    body_path: str,
) -> None:
    """R12e — reconcile_edges must not raise after put→get."""
    record = FixtureIssuesStore(
        backend.root / ".cursor/hooks/state/issue-store-fixture.json"
    ).find_by_unit(project_key, unit_id)
    assert record is not None
    body_edges = parse_edges_block(record.body)
    reconciled = reconcile_edges(body_edges, record.native_links)
    assert reconciled.get("edges") == (body_edges or {}).get("edges")
    got = backend.get(unit_id, body_path)
    assert got.verdict == "ok" and got.content


def test_put_get_preserves_absorbs_on_hybrid_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R12a — put→get round-trip preserves absorbs on hybrid-operator bodies."""
    project_key = "absorbs-r12-basic"
    backend = _fixture_backend(tmp_path, monkeypatch, project_key)
    prd_unit = "094-prd-absorbs-r12-basic"
    prd_path = _default_body_path(prd_unit, "prd")
    gap_targets = ["gap-261", "gap-263"]
    canonical = (
        f"---\n"
        f"id: {prd_unit}\n"
        f"type: prd\n"
        f"status: open\n"
        f"visibility: public\n"
        f"absorbs: [{', '.join(gap_targets)}]\n"
        f"---\n"
        f"# PRD absorbs basic roundtrip\n"
    )
    assert backend.put(prd_unit, prd_path, canonical).verdict == "ok"

    got = backend.get(prd_unit, prd_path)
    assert got.verdict == "ok" and got.content
    roundtrip = parse_absorbs_from_canonical_content(got.content)
    assert set(roundtrip) == set(gap_targets)
    _assert_no_edge_divergence(
        backend, project_key=project_key, unit_id=prd_unit, body_path=prd_path
    )


def test_put_get_preserves_absorbs_above_label_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R12a — >20 absorbs survive put→get via sw-edges (labels capped at 20)."""
    project_key = "absorbs-r12-cap"
    backend = _fixture_backend(tmp_path, monkeypatch, project_key)
    prd_unit = "094-prd-absorbs-r12-cap"
    prd_path = _default_body_path(prd_unit, "prd")
    gap_targets = [f"gap-cap-{i:02d}" for i in range(25)]
    canonical = (
        f"---\n"
        f"id: {prd_unit}\n"
        f"type: prd\n"
        f"status: open\n"
        f"visibility: public\n"
        f"absorbs: [{', '.join(gap_targets)}]\n"
        f"---\n"
        f"# PRD above cap absorbs\n"
    )
    assert backend.put(prd_unit, prd_path, canonical).verdict == "ok"

    got = backend.get(prd_unit, prd_path)
    assert got.verdict == "ok" and got.content
    roundtrip = parse_absorbs_from_canonical_content(got.content)
    assert set(roundtrip) == set(gap_targets)
    _assert_no_edge_divergence(
        backend, project_key=project_key, unit_id=prd_unit, body_path=prd_path
    )


def test_merge_prd_absorbs_semantic_noop_on_alias_rerun() -> None:
    """R12b — alias-normalized absorb merge reports changed=False on re-run."""
    gap_unit = "gap-261-planning-store-absorb"
    prd_body = (
        "---\n"
        "id: 094-prd-semantic-noop\n"
        "type: prd\n"
        "status: open\n"
        "visibility: public\n"
        "absorbs: [gap-261]\n"
        "---\n"
        "# PRD with absorbs\n"
        + build_edges_block([{"rel": "absorbs", "target": "gap-261"}], [])
    )
    merged, changed = _merge_prd_absorbs_frontmatter(prd_body, gap_unit)
    assert changed is False
    assert merged == prd_body


def test_merge_prd_absorbs_semantic_noop_on_set_equivalent_rewrite() -> None:
    """R12b — set-equivalent reorder does not report changed=True."""
    prd_body = (
        "---\n"
        "id: 094-prd-semantic-set\n"
        "type: prd\n"
        "status: open\n"
        "visibility: public\n"
        "absorbs: [gap-261, gap-263]\n"
        "---\n"
        "# PRD\n"
        + build_edges_block(
            [
                {"rel": "absorbs", "target": "gap-261"},
                {"rel": "absorbs", "target": "gap-263"},
            ],
            [],
        )
    )
    merged, changed = _merge_prd_absorbs_frontmatter(prd_body, "gap-263")
    assert changed is False
    assert merged == prd_body


def test_put_get_preserves_edges_and_native_no_edge_divergence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R12e — absorbs put unions into existing depends edges and native links."""
    project_key = "absorbs-r12-edges"
    backend = _fixture_backend(tmp_path, monkeypatch, project_key)
    parent_unit = "gap-parent-r12-edges"
    prd_unit = "094-prd-absorbs-r12-edges"
    backend.put(
        parent_unit,
        _default_body_path(parent_unit, "gap"),
        f"---\nid: {parent_unit}\ntype: gap\nvisibility: public\n---\n# parent\n",
    )

    store = FixtureIssuesStore(backend.root / ".cursor/hooks/state/issue-store-fixture.json")
    parent_rec = store.find_by_unit(project_key, parent_unit)
    assert parent_rec is not None

    edge_list = [{"rel": "depends", "target": parent_unit}]
    native_links = [{"type": "depends-on", "target": parent_rec.id}]
    prd_path = _default_body_path(prd_unit, "prd")
    seed_body = (
        f"---\nid: {prd_unit}\ntype: prd\nstatus: open\nvisibility: public\n---\n# seed\n"
        + build_edges_block(edge_list, native_links)
    )
    assert backend.put(prd_unit, prd_path, seed_body).verdict == "ok"

    canonical = (
        f"---\n"
        f"id: {prd_unit}\n"
        f"type: prd\n"
        f"status: open\n"
        f"visibility: public\n"
        f"absorbs: [gap-264]\n"
        f"depends: [{parent_unit}]\n"
        f"---\n"
        f"# PRD edge union\n"
    )
    assert backend.put(prd_unit, prd_path, canonical).verdict == "ok"

    got = backend.get(prd_unit, prd_path)
    assert got.verdict == "ok" and got.content
    absorbs = parse_absorbs_from_canonical_content(got.content)
    assert "gap-264" in absorbs

    store = FixtureIssuesStore(backend.root / ".cursor/hooks/state/issue-store-fixture.json")
    record = FixtureIssuesStore(
        backend.root / ".cursor/hooks/state/issue-store-fixture.json"
    ).find_by_unit(project_key, prd_unit)
    assert record is not None
    body_edges = parse_edges_block(record.body)
    assert body_edges is not None
    rels = {(e.get("rel"), e.get("target")) for e in body_edges.get("edges") or []}
    assert ("depends", parent_unit) in rels
    assert ("absorbs", "gap-264") in rels
    assert body_edges.get("native") == native_links
    reconciled = reconcile_edges(body_edges, record.native_links)
    assert reconciled.get("native") == native_links
    _assert_no_edge_divergence(
        backend, project_key=project_key, unit_id=prd_unit, body_path=prd_path
    )


def test_put_get_second_roundtrip_preserves_edge_union(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R12e — metadata-only re-put does not drop absorbs or trigger edge-divergence."""
    project_key = "absorbs-r12-reput"
    backend = _fixture_backend(tmp_path, monkeypatch, project_key)
    prd_unit = "094-prd-absorbs-r12-reput"
    prd_path = _default_body_path(prd_unit, "prd")
    canonical = (
        f"---\n"
        f"id: {prd_unit}\n"
        f"type: prd\n"
        f"status: open\n"
        f"visibility: public\n"
        f"absorbs: [gap-261, gap-263]\n"
        f"---\n"
        f"# PRD re-put\n"
    )
    assert backend.put(prd_unit, prd_path, canonical).verdict == "ok"
    first = backend.get(prd_unit, prd_path)
    assert first.verdict == "ok" and first.content

    metadata_only = (
        f"---\n"
        f"id: {prd_unit}\n"
        f"type: prd\n"
        f"status: draft\n"
        f"visibility: public\n"
        f"absorbs: [gap-261, gap-263]\n"
        f"---\n"
        f"# PRD re-put status change\n"
    )
    assert backend.put(prd_unit, prd_path, metadata_only).verdict == "ok"
    second = backend.get(prd_unit, prd_path)
    assert second.verdict == "ok" and second.content
    assert set(parse_absorbs_from_canonical_content(second.content)) == {"gap-261", "gap-263"}
    _assert_no_edge_divergence(
        backend, project_key=project_key, unit_id=prd_unit, body_path=prd_path
    )
