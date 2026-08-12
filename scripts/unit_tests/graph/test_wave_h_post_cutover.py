#!/usr/bin/env python3
"""Post-cutover graph proposal, lineage, and crash/replay fixtures."""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.artifact_registry import ArtifactRegistry  # noqa: E402
from graph.crash_replay_harness import (  # noqa: E402
    CrashPoint,
    CrashReplayHarness,
)
from graph.cutover import CutoverStage, DogfoodEvidence  # noqa: E402
from graph.dynamic_proposal import (  # noqa: E402
    ProposalBudget,
    evaluate_dynamic_proposal,
)
from graph.lineage import (  # noqa: E402
    ArtifactLineageView,
    edge_reduction_advisory,
)
from graph.typed_dataflow import TypedEdge  # noqa: E402


def _node(node_id: str, kind: str = "command") -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "target": {"step": f"sw-{node_id}"},
        "resources": {
            "pool": "code-writers",
            "slots": 1,
            "timeoutSeconds": 30,
        },
        "isolation": {"mode": "worktree", "writeScope": "worktree"},
        "verification": {"required": True, "strategy": "mechanical"},
    }


def _graph(*, include_replay_nodes: bool = False) -> dict[str, Any]:
    nodes = [_node("prepare")]
    edges: list[dict[str, Any]] = []
    if include_replay_nodes:
        nodes.extend([_node("join", "barrier"), _node("iterate", "convergence-loop")])
        edges.extend(
            [
                {"from": "prepare", "to": "join", "required": True},
                {"from": "join", "to": "iterate", "required": True},
            ]
        )
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "post-cutover-fixture"},
        "spec": {
            "nodes": nodes,
            "edges": edges,
            "resourceLimits": {
                "maxConcurrency": 2,
                "maxDurationSeconds": 120,
            },
            "verification": {"required": True, "failClosed": True},
        },
    }


def _budget() -> ProposalBudget:
    return ProposalBudget(
        max_nodes=4,
        max_edges=4,
        max_concurrency=4,
        max_duration_seconds=300,
        max_total_slots=4,
    )


def test_dynamic_proposal_rejects_to_canonical_and_accepts_guarded_graph() -> None:
    canonical = _graph()
    invalid = deepcopy(canonical)
    invalid["spec"]["nodes"][0]["kind"] = "agent-python"

    fallback = evaluate_dynamic_proposal(
        invalid,
        canonical_graph=canonical,
        plan_policy="proposed",
        cutover_stage=CutoverStage.FULL,
        cutover_evidence=DogfoodEvidence.passing(completed_runs=3),
        budget=_budget(),
    )
    assert fallback.verdict == "canonical-fallback"
    assert fallback.used_fallback is True
    assert fallback.graph == canonical
    assert "unknown node kind" in fallback.reason

    accepted = evaluate_dynamic_proposal(
        canonical,
        canonical_graph=canonical,
        plan_policy="proposed",
        cutover_stage=CutoverStage.FULL,
        cutover_evidence=DogfoodEvidence.passing(completed_runs=3),
        budget=_budget(),
    )
    assert accepted.verdict == "accepted"
    assert accepted.used_fallback is False


def test_dynamic_proposal_is_inactive_before_green_cutover_and_checks_budget() -> None:
    canonical = _graph()
    inactive = evaluate_dynamic_proposal(
        canonical,
        canonical_graph=canonical,
        plan_policy="proposed",
        cutover_stage=CutoverStage.LIMITED,
        cutover_evidence=DogfoodEvidence.passing(completed_runs=3),
        budget=_budget(),
    )
    assert inactive.used_fallback is True
    assert "inactive" in inactive.reason

    oversized = deepcopy(canonical)
    oversized["spec"]["resourceLimits"]["maxDurationSeconds"] = 301
    rejected = evaluate_dynamic_proposal(
        oversized,
        canonical_graph=canonical,
        plan_policy="proposed",
        cutover_stage=CutoverStage.FULL,
        cutover_evidence=DogfoodEvidence.passing(completed_runs=3),
        budget=_budget(),
    )
    assert rejected.used_fallback is True
    assert "exceeds budget" in rejected.reason


def _receipt(node_id: str, model: str) -> dict[str, Any]:
    return {
        "nodeId": node_id,
        "model": model,
        "attempts": 1,
        "inputHashes": [],
        "outputHashes": [],
        "verdict": "pass",
    }


def test_lineage_query_and_edge_reduction_advice_are_non_destructive(
    tmp_path: Path,
) -> None:
    registry = ArtifactRegistry(tmp_path / "artifacts")
    registry.register(
        artifact_id="source",
        content={"value": 1},
        schema="fixture/source",
        producing_node="collect",
        input_revision="revision-1",
        verification_evidence=["collect-check"],
    )
    registry.register(
        artifact_id="result",
        content={"value": 2},
        schema="fixture/result",
        producing_node="verify",
        input_revision="revision-1",
        verification_evidence=["verify-check"],
    )
    edges = (
        TypedEdge("source-to-verify", "collect", "verify", "source", "fixture/source"),
        TypedEdge("duplicate", "collect", "verify", "source", "fixture/source", required=False),
        TypedEdge("protected", "lock", "verify", "", "fixture/control", required=False),
    )
    view = ArtifactLineageView(
        registry,
        edges,
        [_receipt("collect", "build-model"), _receipt("verify", "deep-model")],
    )

    result = view.query("result")
    assert result.producing_node == "verify"
    assert result.model == "deep-model"
    assert result.input_artifacts == ("source",)
    assert [item.artifact_id for item in view.chain("result")] == ["source", "result"]

    original_edges = edges
    advice = edge_reduction_advisory(
        edges,
        consumed_edge_ids={"source-to-verify"},
        contention_relevant_edge_ids={"protected"},
    )
    by_id = {item["edgeId"]: item for item in advice}
    assert by_id["duplicate"]["recommendation"] == "review-for-removal"
    assert by_id["protected"]["recommendation"] == "keep"
    assert by_id["protected"]["reason"] == "contention-relevant"
    assert edges == original_edges
    assert all(item["action"] == "advisory-only" for item in advice)


@pytest.mark.parametrize("crash_point", list(CrashPoint))
def test_resume_from_durable_evidence_has_no_duplicate_side_effects(
    tmp_path: Path,
    crash_point: CrashPoint,
) -> None:
    harness = CrashReplayHarness(
        _graph(include_replay_nodes=True),
        root=tmp_path / crash_point.value,
        kernel_options={
            "loop_bounds": {
                "iterate": {"maxRounds": 3, "maxFindings": 2, "maxTokens": 5}
            }
        },
    )
    report = harness.run(crash_point, run_id=f"fixture-{crash_point.value}")

    assert report.resumed is True
    assert report.verdict == "pass"
    assert report.chat_history_used is False
    assert report.duplicate_side_effects == ()
    assert all(count == 1 for count in report.side_effect_counts.values())
    if crash_point is not CrashPoint.MID_NODE:
        assert "prepare" in report.replayed_nodes
