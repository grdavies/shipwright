#!/usr/bin/env python3
"""DecisionGraph frontier ready-set unit tests (PRD 280 R4/R5)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from decision_graph.frontier import compute_frontier, detect_cycle, frontier_for_unit  # noqa: E402
from decision_graph.schema import NodeKind, ValidationErrorCode, minimal_fixture_graph  # noqa: E402


def _graph(*, nodes: list[dict], edges: list[dict]) -> dict:
    doc = minimal_fixture_graph()
    doc["spec"]["nodes"] = nodes
    doc["spec"]["edges"] = edges
    return doc


def test_no_deps_single_ready() -> None:
    graph = _graph(
        nodes=[
            {"id": "d1", "kind": NodeKind.DECISION.value, "status": "open", "question": "Q?"},
        ],
        edges=[],
    )
    result = compute_frontier(graph)
    assert result["verdict"] == "pass"
    assert result["ready"] == ["d1"]
    assert result["blocked"] == []


def test_chain_only_head_ready() -> None:
    graph = _graph(
        nodes=[
            {"id": "a", "kind": NodeKind.RESEARCH.value, "status": "open", "topic": "t1"},
            {"id": "b", "kind": NodeKind.RESEARCH.value, "status": "open", "topic": "t2"},
            {"id": "c", "kind": NodeKind.RESEARCH.value, "status": "open", "topic": "t3"},
        ],
        edges=[{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
    )
    result = compute_frontier(graph)
    assert result["ready"] == ["a"]
    assert {item["id"] for item in result["blocked"]} == {"b", "c"}


def test_chain_advances_after_resolution() -> None:
    graph = _graph(
        nodes=[
            {"id": "a", "kind": NodeKind.RESEARCH.value, "status": "resolved", "topic": "t1"},
            {"id": "b", "kind": NodeKind.RESEARCH.value, "status": "open", "topic": "t2"},
            {"id": "c", "kind": NodeKind.RESEARCH.value, "status": "open", "topic": "t3"},
        ],
        edges=[{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
    )
    result = compute_frontier(graph)
    assert result["ready"] == ["b"]


def test_diamond_ready_set() -> None:
    graph = _graph(
        nodes=[
            {"id": "a", "kind": NodeKind.DECISION.value, "status": "resolved", "question": "root"},
            {"id": "b", "kind": NodeKind.RESEARCH.value, "status": "open", "topic": "left"},
            {"id": "c", "kind": NodeKind.RESEARCH.value, "status": "open", "topic": "right"},
            {"id": "d", "kind": NodeKind.PROTOTYPE.value, "status": "open", "title": "merge"},
        ],
        edges=[
            {"from": "a", "to": "b"},
            {"from": "a", "to": "c"},
            {"from": "b", "to": "d"},
            {"from": "c", "to": "d"},
        ],
    )
    result = compute_frontier(graph)
    assert result["ready"] == ["b", "c"]

    graph["spec"]["nodes"][1]["status"] = "resolved"
    graph["spec"]["nodes"][2]["status"] = "resolved"
    result = compute_frontier(graph)
    assert result["ready"] == ["d"]


def test_cycle_fails_closed() -> None:
    graph = _graph(
        nodes=[
            {"id": "a", "kind": NodeKind.RESEARCH.value, "status": "open", "topic": "t1"},
            {"id": "b", "kind": NodeKind.RESEARCH.value, "status": "open", "topic": "t2"},
        ],
        edges=[{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
    )
    assert detect_cycle(graph) is True
    result = compute_frontier(graph)
    assert result["verdict"] == "fail"
    assert result["error"] == ValidationErrorCode.GRAPH_CYCLE.value


def test_cancelled_predecessor_blocks_successor() -> None:
    graph = _graph(
        nodes=[
            {"id": "a", "kind": NodeKind.DECISION.value, "status": "cancelled", "question": "dropped"},
            {"id": "b", "kind": NodeKind.RESEARCH.value, "status": "open", "topic": "follow-up"},
            {
                "id": "h1",
                "kind": NodeKind.HUMAN_ACTION.value,
                "status": "open",
                "title": "Manual gate",
            },
        ],
        edges=[{"from": "a", "to": "b"}, {"from": "b", "to": "h1"}],
    )
    result = compute_frontier(graph)
    assert result["ready"] == []
    blocked = {item["id"]: item["reason"] for item in result["blocked"]}
    assert blocked["b"] == "cancelled-predecessor"
    assert blocked["h1"] == "unresolved-predecessor"


def test_mixed_kinds_open_frontier() -> None:
    graph = _graph(
        nodes=[
            {"id": "d1", "kind": NodeKind.DECISION.value, "status": "open", "question": "Q?"},
            {"id": "r1", "kind": NodeKind.RESEARCH.value, "status": "open", "topic": "topic"},
            {
                "id": "h1",
                "kind": NodeKind.HUMAN_ACTION.value,
                "status": "open",
                "title": "Approve deploy",
            },
        ],
        edges=[],
    )
    result = compute_frontier(graph)
    assert result["ready"] == ["d1", "h1", "r1"]


def test_decision_frontier_cli_read_only(tmp_path: Path) -> None:
    graph_path = tmp_path / "decision-graph.json"
    graph = minimal_fixture_graph()
    graph["metadata"]["unitId"] = "unit-fixture"
    graph_path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")

    result = frontier_for_unit(tmp_path, "unit-fixture", graph_path=graph_path)
    assert result["verdict"] == "pass"
    assert result["ready"] == ["d1"]
    assert result["unitId"] == "unit-fixture"
    assert result["graphPath"] == str(graph_path)


def test_decision_frontier_cli_via_planning_graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    graph_path = tmp_path / "fixture.json"
    graph = minimal_fixture_graph()
    graph["metadata"]["unitId"] = "280-prd-engineering-decision-layer"
    graph_path.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "planning_graph_mod",
        _SCRIPTS / "planning-graph.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = mod.cmd_decision_frontier(
            tmp_path,
            ["--unit-id", "280-prd-engineering-decision-layer", "--graph", str(graph_path)],
        )
    assert code == 0
    payload = json.loads(buffer.getvalue())
    assert payload["verdict"] == "pass"
    assert payload["readyCount"] == 1
