#!/usr/bin/env python3
"""Kernel guards, prototype isolation, and evidence link-back tests (PRD 280 phase 3)."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from decision_graph.evidence import (  # noqa: E402
    build_evidence_record,
    extract_and_link,
    link_evidence_to_decision,
)
from decision_graph.prototype import (  # noqa: E402
    CAUSE_MARKER_INVALID,
    is_prototype_branch,
    prototype_branch_name,
    refuse_merge_enqueue,
)
from decision_graph.schema import NodeKind, minimal_fixture_graph  # noqa: E402
from decision_graph_guard import (  # noqa: E402
    CAUSE_ACTIVE_BLOCKS_WRITE,
    check_mutating_dispatch,
    check_production_write,
)


def _graph_with_open_decision() -> dict:
    graph = minimal_fixture_graph()
    graph["spec"]["nodes"] = [
        {
            "id": "d1",
            "kind": NodeKind.DECISION.value,
            "status": "open",
            "question": "Which backend?",
        }
    ]
    return graph


def test_active_decision_blocks_production_write() -> None:
    result = check_production_write(_graph_with_open_decision(), ["scripts/foo.py"])
    assert result["verdict"] == "fail"
    assert result["cause"] == CAUSE_ACTIVE_BLOCKS_WRITE


def test_resolved_decision_allows_write() -> None:
    graph = _graph_with_open_decision()
    graph["spec"]["nodes"][0]["status"] = "resolved"
    graph["spec"]["nodes"][0]["resolution"] = {"outcome": "pick-a"}
    result = check_production_write(graph, ["scripts/foo.py"])
    assert result["verdict"] == "pass"


def test_read_only_dispatch_allowed_with_active_nodes() -> None:
    result = check_mutating_dispatch(_graph_with_open_decision(), mutating=False)
    assert result["verdict"] == "pass"


def test_prototype_branch_detection_and_merge_refusal() -> None:
    branch = prototype_branch_name("spike-auth")
    assert is_prototype_branch(branch)
    refusal = refuse_merge_enqueue(branch, "feat/engineering-decision-layer")
    assert refusal["verdict"] == "fail"
    assert refusal["cause"] == CAUSE_MARKER_INVALID


def test_normal_phase_branch_merge_enqueue_allowed() -> None:
    branch = "feat/engineering-decision-layer-phase-demo"
    refusal = refuse_merge_enqueue(branch, "feat/engineering-decision-layer")
    assert refusal["verdict"] == "pass"


def test_evidence_link_back_updates_parent_decision() -> None:
    graph = minimal_fixture_graph()
    record = build_evidence_record(
        parent_decision_id="d1",
        prototype_node_id="p1",
        head_sha="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        content_hash="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        branch="feat/prototype-p1",
    )
    linked = link_evidence_to_decision(graph, "d1", record)
    assert linked["verdict"] == "pass"
    node = linked["graph"]["spec"]["nodes"][0]
    assert node["status"] == "resolved"
    assert str(node["resolution"]["outcome"]).startswith("evidence:")


def test_extract_and_link_writes_evidence_file(tmp_path: Path) -> None:
    graph = deepcopy(minimal_fixture_graph())
    graph["spec"]["nodes"].append(
        {
            "id": "p1",
            "kind": NodeKind.PROTOTYPE.value,
            "status": "open",
            "title": "Spike",
        }
    )
    graph["spec"]["edges"] = [{"from": "d1", "to": "p1"}]
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").mkdir()
    result = extract_and_link(
        tmp_path,
        graph,
        wt,
        parent_decision_id="d1",
        prototype_node_id="p1",
        branch="feat/prototype-p1",
        base_ref="HEAD",
    )
    assert result["verdict"] == "pass"
    evidence_path = Path(result["evidencePath"])
    assert evidence_path.is_file()
    stored = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert stored["metadata"]["parentDecisionId"] == "d1"
