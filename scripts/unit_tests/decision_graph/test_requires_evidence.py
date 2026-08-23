#!/usr/bin/env python3
"""requiresEvidence node flag, guard, validate, and frontier tests (PRD 326 R7)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from decision_graph.evidence import (  # noqa: E402
    REASON_EVIDENCE_REQUIRED,
    build_evidence_record,
    check_evidence_required,
    has_linked_evidence,
    write_evidence_record,
)
from decision_graph.frontier import compute_frontier  # noqa: E402
from decision_graph.schema import NodeKind, minimal_fixture_graph  # noqa: E402


def _graph_with_requires_evidence(*, status: str = "open") -> dict:
    graph = minimal_fixture_graph()
    node = graph["spec"]["nodes"][0]
    node["requiresEvidence"] = True
    node["status"] = status
    if status == "resolved":
        node["resolution"] = {"outcome": "picked-without-evidence"}
    return graph


def test_resolved_requires_evidence_without_records_fails(tmp_path: Path) -> None:
    result = check_evidence_required(_graph_with_requires_evidence(status="resolved"), tmp_path)
    assert result == {"verdict": "fail", "reason": REASON_EVIDENCE_REQUIRED, "nodeId": "d1"}


def test_resolved_requires_evidence_with_linked_record_passes(tmp_path: Path) -> None:
    graph = _graph_with_requires_evidence(status="resolved")
    record = build_evidence_record(
        parent_decision_id="d1",
        prototype_node_id="p1",
        head_sha="a" * 40,
        content_hash="b" * 64,
        branch="feat/prototype-p1",
    )
    write_evidence_record(tmp_path, record)
    assert has_linked_evidence(tmp_path, "d1")
    result = check_evidence_required(graph, tmp_path)
    assert result["verdict"] == "pass"


def test_requires_evidence_false_backward_compatible(tmp_path: Path) -> None:
    graph = minimal_fixture_graph()
    graph["spec"]["nodes"][0]["status"] = "resolved"
    graph["spec"]["nodes"][0]["resolution"] = {"outcome": "no-evidence-needed"}
    result = check_evidence_required(graph, tmp_path)
    assert result["verdict"] == "pass"


def test_frontier_blocks_open_requires_evidence_without_records(tmp_path: Path) -> None:
    graph = _graph_with_requires_evidence(status="open")
    result = compute_frontier(graph, root=tmp_path)
    assert result["verdict"] == "pass"
    assert result["ready"] == []
    assert result["blocked"] == [
        {
            "id": "d1",
            "reason": REASON_EVIDENCE_REQUIRED,
            "blockedBy": REASON_EVIDENCE_REQUIRED,
        }
    ]


def test_frontier_ready_when_evidence_linked(tmp_path: Path) -> None:
    graph = _graph_with_requires_evidence(status="open")
    record = build_evidence_record(
        parent_decision_id="d1",
        prototype_node_id="p1",
        head_sha="a" * 40,
        content_hash="b" * 64,
        branch="feat/prototype-p1",
    )
    write_evidence_record(tmp_path, record)
    result = compute_frontier(graph, root=tmp_path)
    assert result["ready"] == ["d1"]


def test_validate_cli_require_evidence_exit_20(tmp_path: Path) -> None:
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(_graph_with_requires_evidence(status="resolved")) + "\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "decision_graph" / "validate.py"), "--graph", str(graph_path), "--require-evidence", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 20
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "fail"
    assert payload["reason"] == REASON_EVIDENCE_REQUIRED
    assert payload["nodeId"] == "d1"


def test_guard_cli_require_evidence_exit_20(tmp_path: Path) -> None:
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(_graph_with_requires_evidence(status="resolved")) + "\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "decision_graph_guard.py"), "--graph", str(graph_path), "--require-evidence", "--root", str(tmp_path), "--read-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 20
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "fail"
    assert payload["reason"] == REASON_EVIDENCE_REQUIRED
    assert payload["nodeId"] == "d1"
