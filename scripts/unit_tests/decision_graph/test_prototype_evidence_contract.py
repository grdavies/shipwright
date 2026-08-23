#!/usr/bin/env python3
"""Prototype evidence contract closure tests (PRD 326 R8)."""
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
    KIND_PROTOTYPE,
    build_evidence_record,
    write_evidence_record,
)
from decision_graph.journal import DecisionRunJournal  # noqa: E402
from decision_graph.prototype import (  # noqa: E402
    CAUSE_EVIDENCE_MISSING,
    CAUSE_MARKER_INVALID,
    prototype_branch_name,
    read_prototype_marker,
    refuse_merge_enqueue,
    teardown_prototype_worktree,
    write_prototype_marker,
)
from decision_graph.receipt import validate_prototype_teardown_receipt  # noqa: E402
from decision_graph.schema import NodeKind, minimal_fixture_graph  # noqa: E402


def _graph_with_prototype(*, parent_requires_evidence: bool = True) -> dict:
    graph = deepcopy(minimal_fixture_graph())
    graph["spec"]["nodes"][0]["requiresEvidence"] = parent_requires_evidence
    graph["spec"]["nodes"].append(
        {
            "id": "p1",
            "kind": NodeKind.PROTOTYPE.value,
            "status": "open",
            "title": "Spike",
        }
    )
    graph["spec"]["edges"] = [{"from": "d1", "to": "p1"}]
    return graph


def _write_marker(
    worktree: Path,
    *,
    parent_requires_evidence: bool = True,
    parent_decision_id: str = "d1",
    node_id: str = "p1",
) -> None:
    write_prototype_marker(
        worktree,
        node_id=node_id,
        parent_decision_id=parent_decision_id,
        branch=prototype_branch_name(node_id),
        parent_branch="feat/integration",
        parent_requires_evidence=parent_requires_evidence,
        required_evidence_kind=KIND_PROTOTYPE,
    )


def test_read_rejects_marker_without_evidence_contract(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    marker = wt / ".cursor" / "sw-prototype.json"
    marker.parent.mkdir(parents=True)
    marker.write_text(
        json.dumps(
            {
                "kind": "prototype-worktree",
                "nodeId": "p1",
                "parentDecisionId": "d1",
                "branch": "feat/prototype-p1",
                "parentBranch": "feat/integration",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert read_prototype_marker(wt) is None


def test_marker_round_trips_evidence_contract(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _write_marker(wt, parent_requires_evidence=True)
    marker = read_prototype_marker(wt)
    assert marker is not None
    contract = marker["evidenceContract"]
    assert contract["requiredEvidenceKind"] == KIND_PROTOTYPE
    assert contract["parentRequiresEvidence"] is True


def test_refuse_merge_enqueue_names_missing_kind(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _write_marker(wt, parent_requires_evidence=True)
    branch = prototype_branch_name("p1")
    refusal = refuse_merge_enqueue(
        branch,
        "feat/workflow-quality-platform",
        root=tmp_path,
        worktree=wt,
    )
    assert refusal["verdict"] == "fail"
    assert refusal["cause"] == CAUSE_EVIDENCE_MISSING
    assert refusal["missingEvidenceKind"] == KIND_PROTOTYPE
    assert refusal["parentDecisionId"] == "d1"


def test_refuse_merge_enqueue_allows_satisfied_contract(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _write_marker(wt, parent_requires_evidence=True)
    record = build_evidence_record(
        parent_decision_id="d1",
        prototype_node_id="p1",
        head_sha="a" * 40,
        content_hash="b" * 64,
        branch=prototype_branch_name("p1"),
    )
    write_evidence_record(tmp_path, record)
    branch = prototype_branch_name("p1")
    result = refuse_merge_enqueue(
        branch,
        "feat/workflow-quality-platform",
        root=tmp_path,
        worktree=wt,
    )
    assert result["verdict"] == "pass"


def test_refuse_merge_enqueue_parent_not_requires_evidence(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _write_marker(wt, parent_requires_evidence=False)
    branch = prototype_branch_name("p1")
    result = refuse_merge_enqueue(
        branch,
        "feat/workflow-quality-platform",
        root=tmp_path,
        worktree=wt,
    )
    assert result["verdict"] == "pass"


def test_refuse_merge_enqueue_without_marker_fails_closed() -> None:
    branch = prototype_branch_name("p1")
    refusal = refuse_merge_enqueue(branch, "feat/workflow-quality-platform")
    assert refusal["verdict"] == "fail"
    assert refusal["cause"] == CAUSE_MARKER_INVALID


def test_multiple_prototypes_share_parent_evidence(tmp_path: Path) -> None:
    record = build_evidence_record(
        parent_decision_id="d1",
        prototype_node_id="p1",
        head_sha="a" * 40,
        content_hash="b" * 64,
        branch=prototype_branch_name("p1"),
    )
    write_evidence_record(tmp_path, record)

    for node_id in ("p1", "p2", "p3"):
        wt = tmp_path / f"wt-{node_id}"
        wt.mkdir()
        _write_marker(wt, parent_requires_evidence=True, node_id=node_id)
        branch = prototype_branch_name(node_id)
        result = refuse_merge_enqueue(
            branch,
            "feat/workflow-quality-platform",
            root=tmp_path,
            worktree=wt,
        )
        assert result["verdict"] == "pass"


def test_teardown_receipt_and_journal_survive_worktree_removal(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    wt = root / "prototype-wt"
    wt.mkdir()
    (wt / ".git").mkdir()
    _write_marker(wt)

    graph = _graph_with_prototype(parent_requires_evidence=True)
    run_id = "decision-run-prototype-p1"
    result = teardown_prototype_worktree(
        root,
        wt,
        graph,
        run_id=run_id,
        actor="operator",
        base_ref="HEAD",
    )
    assert result["verdict"] == "pass"
    receipt = result["receipt"]
    assert validate_prototype_teardown_receipt(receipt)["verdict"] == "pass"
    assert receipt["evidenceHashes"]

    journal_path = root / ".cursor" / "sw-decision-runs" / run_id
    assert journal_path.is_dir()

    import shutil

    shutil.rmtree(wt)
    assert not wt.exists()

    journal = DecisionRunJournal(root, run_id)
    events = journal.list_events()
    assert len(events) == 1
    assert events[0]["eventType"] == "prototype-teardown"
    assert events[0]["receipt"]["evidenceHashes"] == receipt["evidenceHashes"]
