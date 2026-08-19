"""Unit tests for DecisionGraph issue-store projection (PRD 280 phase 5)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from decision_graph.schema import minimal_fixture_graph
from planning.identity import (
    DECISION_ISSUE_TYPE_LABEL,
    decision_graph_unit_id,
    decision_graph_virtual_body_path,
    resolve_decision_put_path,
)
from planning_graph.decision_projection import (
    DECISION_GRAPH_EDGE_REL,
    decision_graph_edge,
    decision_graph_target_from_edges,
    merge_decision_graph_edge,
    put_decision_graph,
    project_prd_decision_graph_link,
)
from issues_lib import FixtureIssuesStore
from planning_canonical import parse_edges_block
from planning_store import IssueStoreBackend
from planning_store_facade import _default_body_path


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "decision-projection-280") -> dict:
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


def test_decision_issue_type_label_constant() -> None:
    assert DECISION_ISSUE_TYPE_LABEL == "sw:decision"


def test_decision_graph_unit_id_derivation() -> None:
    assert decision_graph_unit_id("280-prd-engineering-decision-layer") == (
        "280-prd-engineering-decision-layer-decision-graph"
    )
    assert (
        decision_graph_unit_id("280-prd-engineering-decision-layer-decision-graph")
        == "280-prd-engineering-decision-layer-decision-graph"
    )


def test_decision_graph_virtual_body_path() -> None:
    uid = "280-prd-engineering-decision-layer-decision-graph"
    assert decision_graph_virtual_body_path(uid) == (
        "docs/planning/decision/280-prd-engineering-decision-layer-decision-graph/decision-graph.json"
    )


def test_resolve_decision_put_path_normalizes_graph() -> None:
    uid = "280-prd-engineering-decision-layer-decision-graph"
    path = decision_graph_virtual_body_path(uid)
    assert resolve_decision_put_path(uid, path) == (uid, path)


def test_default_body_path_decision_graph() -> None:
    uid = "280-prd-engineering-decision-layer-decision-graph"
    assert _default_body_path(uid, "decision") == decision_graph_virtual_body_path(uid)


def test_decision_graph_edge_round_trip() -> None:
    edge = decision_graph_edge("280-prd-engineering-decision-layer-decision-graph")
    assert edge["rel"] == DECISION_GRAPH_EDGE_REL
    assert (
        decision_graph_target_from_edges([edge])
        == "280-prd-engineering-decision-layer-decision-graph"
    )


def test_merge_decision_graph_edge_appends_sw_edges() -> None:
    body = "# PRD\n\nOverview\n"
    updated, changed = merge_decision_graph_edge(
        body,
        "280-prd-engineering-decision-layer-decision-graph",
    )
    assert changed
    assert "```sw-edges" in updated
    assert DECISION_GRAPH_EDGE_REL in updated


def test_merge_decision_graph_edge_idempotent() -> None:
    body = "# PRD\n\nOverview\n"
    updated, _ = merge_decision_graph_edge(
        body,
        "280-prd-engineering-decision-layer-decision-graph",
    )
    again, changed = merge_decision_graph_edge(
        updated,
        "280-prd-engineering-decision-layer-decision-graph",
    )
    assert not changed
    assert again == updated


def test_put_decision_graph_issue_store_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg()
    (root / ".cursor" / "workflow.config.json").write_text(
        json.dumps(cfg),
        encoding="utf-8",
    )

    prd_unit = "280-prd-engineering-decision-layer"
    graph = minimal_fixture_graph()
    result = put_decision_graph(root, prd_unit, graph)
    assert result["verdict"] == "ok"
    assert result["graphUnitId"] == decision_graph_unit_id(prd_unit)
    assert result["bodyPath"] == decision_graph_virtual_body_path(result["graphUnitId"])


def test_project_prd_decision_graph_link_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg()
    (root / ".cursor" / "workflow.config.json").write_text(
        json.dumps(cfg),
        encoding="utf-8",
    )

    prd_unit = "280-prd-engineering-decision-layer"
    prd_path = "docs/prds/280-engineering-decision-layer/280-prd-engineering-decision-layer.md"
    import planning_artifact_handle as pah

    put = pah.put_artifact_text(
        root,
        prd_unit,
        prd_path,
        "---\nid: x\nvisibility: public\n---\n# PRD\n",
    )
    assert put["verdict"] == "ok"

    link = project_prd_decision_graph_link(root, prd_unit, prd_path)
    assert link["verdict"] == "pass"
    assert not link.get("skipped")
    assert link["graphUnitId"] == decision_graph_unit_id(prd_unit)

    backend = IssueStoreBackend(root, cfg)
    got = backend.get(prd_unit, prd_path)
    assert got.verdict == "ok" and got.content

    prd_rec = FixtureIssuesStore(
        root / ".cursor/hooks/state/issue-store-fixture.json"
    ).find_by_unit(cfg["planning"]["store"]["projectKey"], prd_unit)
    assert prd_rec is not None
    edges_block = parse_edges_block(prd_rec.body)
    assert edges_block is not None
    assert (
        decision_graph_target_from_edges(list(edges_block.get("edges") or []))
        == decision_graph_unit_id(prd_unit)
    )
