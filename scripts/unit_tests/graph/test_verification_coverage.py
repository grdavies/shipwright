#!/usr/bin/env python3
"""PRD 272 phase-5 required-capability coverage semantics tests (R16)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.cutover import CutoverStage, DogfoodEvidence  # noqa: E402
from graph.detectors.registry import CAPABILITY_AUTH  # noqa: E402
from graph.dynamic_proposal import (  # noqa: E402
    ProposalBudget,
    assert_coverage_regression_gate,
    compute_graph_capability_coverage,
    compute_verification_coverage,
    evaluate_dynamic_proposal,
    measure_verifier_substitution_regression,
    CoverageEvidenceRecord,
    CoverageRequirement,
)
from graph.verifier_policies import VerifierKind  # noqa: E402


def _node(node_id: str, kind: str = "command", *, strategy: str = "mechanical") -> dict[str, Any]:
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
        "verification": {"required": True, "strategy": strategy},
    }


def _auth_coverage_graph(*, strategy: str) -> dict[str, Any]:
    auth_node = _node("sw-verify-auth", "verifier", strategy=strategy)
    auth_node["target"] = {"step": "sw-verify-auth"}
    nodes = [
        _node("prepare"),
        auth_node,
        _node("merge-gate", "gate"),
        _node("credential-broker"),
        _node("write-isolation-lease"),
    ]
    edges = [
        {"from": "prepare", "to": "sw-verify-auth", "required": True},
        {"from": "sw-verify-auth", "to": "merge-gate", "required": True},
        {"from": "merge-gate", "to": "credential-broker", "required": True},
        {"from": "credential-broker", "to": "write-isolation-lease", "required": True},
    ]
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "coverage-fixture"},
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


def _graph_with_verifiers(*nodes: dict[str, Any]) -> dict[str, Any]:
    strategy = str((nodes[0].get("verification") or {}).get("strategy") or "mechanical")
    cap_id = str((nodes[0].get("metadata") or {}).get("requiredCapabilityId") or CAPABILITY_AUTH)
    return _auth_coverage_graph(strategy=strategy)


def _legacy_required_ratio(graph: dict[str, Any]) -> float:
    required = 0
    covered = 0
    for node in graph["spec"]["nodes"]:
        if node.get("kind") not in {"verifier", "gate"}:
            continue
        required += 1
        if bool((node.get("verification") or {}).get("required")):
            covered += 1
    return 1.0 if required == 0 else covered / required


def test_coverage_regression_on_weaker_verifier_swap() -> None:
    canonical = _auth_coverage_graph(strategy=VerifierKind.JUDGMENT.value)
    weaker = _auth_coverage_graph(strategy=VerifierKind.MECHANICAL.value)

    assert _legacy_required_ratio(canonical) == 1.0
    assert _legacy_required_ratio(weaker) == 1.0

    canonical_coverage = compute_graph_capability_coverage(
        canonical,
        reference_graph=canonical,
    )
    weaker_coverage = compute_graph_capability_coverage(
        weaker,
        reference_graph=canonical,
    )
    assert canonical_coverage.aggregate == 1.0
    assert weaker_coverage.aggregate < 1.0
    assert weaker_coverage.by_capability_id[CAPABILITY_AUTH] < 1.0

    requirements = (
        CoverageRequirement(
            capability_id=CAPABILITY_AUTH,
            acceptance_criterion_id=f"{CAPABILITY_AUTH}:default",
            required_verifier_class=VerifierKind.JUDGMENT.value,
        ),
    )
    strong_evidence = (
        CoverageEvidenceRecord(
            capability_id=CAPABILITY_AUTH,
            acceptance_criterion_id=f"{CAPABILITY_AUTH}:default",
            verifier_class=VerifierKind.JUDGMENT.value,
            passed=True,
            head_sha="abc123",
        ),
    )
    weak_evidence = (
        CoverageEvidenceRecord(
            capability_id=CAPABILITY_AUTH,
            acceptance_criterion_id=f"{CAPABILITY_AUTH}:default",
            verifier_class=VerifierKind.MECHANICAL.value,
            passed=True,
            head_sha="abc123",
        ),
    )
    delta = measure_verifier_substitution_regression(
        requirements=requirements,
        strong_evidence=strong_evidence,
        weak_evidence=weak_evidence,
        head_sha="abc123",
    )
    assert delta < 0.0

    legacy_verification = compute_verification_coverage(
        weaker,
        reference_graph=canonical,
    )
    assert legacy_verification.aggregate < 1.0

    with pytest.raises(ValueError, match="coverage regression"):
        assert_coverage_regression_gate(weaker, canonical_graph=canonical)


def test_evaluate_dynamic_proposal_uses_required_capability_coverage_gate() -> None:
    canonical = _auth_coverage_graph(strategy=VerifierKind.JUDGMENT.value)
    weaker = _auth_coverage_graph(strategy=VerifierKind.MECHANICAL.value)
    budget = ProposalBudget(
        max_nodes=8,
        max_edges=8,
        max_concurrency=4,
        max_duration_seconds=300,
        max_total_slots=8,
    )
    evidence = DogfoodEvidence.passing(completed_runs=3)
    decision = evaluate_dynamic_proposal(
        weaker,
        canonical_graph=canonical,
        plan_policy="proposed",
        cutover_stage=CutoverStage.FULL,
        cutover_evidence=evidence,
        budget=budget,
    )
    assert decision.used_fallback is True
    assert "coverage regression" in decision.reason
