#!/usr/bin/env python3
"""PRD 272 phase-2 required-capability topology tests."""
from __future__ import annotations

import sys
from copy import deepcopy
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
    assert_auth_capabilities_nonskippable,
    assert_required_capability_topology,
    evaluate_dynamic_proposal,
)
from graph.workflow_library import (  # noqa: E402
    assert_control_path_preserves_auth,
    required_capabilities_from_graph,
)


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


def _required_capability_graph() -> dict[str, Any]:
    nodes = [
        _node("prepare"),
        _node("mechanical-verification", "verifier"),
        _node("merge-gate", "gate"),
        _node("credential-broker"),
        _node("write-isolation-lease"),
    ]
    edges = [
        {"from": "prepare", "to": "mechanical-verification", "required": True},
        {"from": "mechanical-verification", "to": "merge-gate", "required": True},
        {"from": "merge-gate", "to": "credential-broker", "required": True},
        {"from": "credential-broker", "to": "write-isolation-lease", "required": True},
    ]
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "topology-fixture"},
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


def _green_proposal_kwargs() -> dict[str, Any]:
    return {
        "plan_policy": "proposed",
        "cutover_stage": CutoverStage.FULL,
        "cutover_evidence": DogfoodEvidence.passing(completed_runs=3),
        "budget": ProposalBudget(
            max_nodes=8,
            max_edges=8,
            max_concurrency=4,
            max_duration_seconds=300,
            max_total_slots=8,
        ),
    }


def test_required_capability_edge_strip_rejected() -> None:
    canonical = _required_capability_graph()
    stripped = deepcopy(canonical)
    stripped["spec"]["edges"] = [
        edge
        for edge in stripped["spec"]["edges"]
        if edge["to"] != "merge-gate"
    ]
    with pytest.raises(ValueError, match="inbound edges"):
        assert_required_capability_topology(stripped, canonical)

    decision = evaluate_dynamic_proposal(
        stripped,
        canonical_graph=canonical,
        **_green_proposal_kwargs(),
    )
    assert decision.used_fallback is True
    assert "inbound edges" in decision.reason or "required-capability" in decision.reason


def test_auth_cap_not_skipped_by_budget_or_profile() -> None:
    graph = _required_capability_graph()
    auth_node = _node("sw-verify-auth", "verifier")
    auth_node["metadata"] = {"requiredCapabilityId": CAPABILITY_AUTH}
    auth_node["target"] = {"step": "sw-verify-auth"}
    graph["spec"]["nodes"].insert(1, auth_node)
    graph["spec"]["edges"].insert(
        0,
        {"from": "prepare", "to": "sw-verify-auth", "required": True},
    )
    graph["spec"]["edges"][1]["from"] = "sw-verify-auth"

    baseline_caps = required_capabilities_from_graph(graph)
    assert CAPABILITY_AUTH in baseline_caps

    without_auth = deepcopy(graph)
    without_auth["spec"]["nodes"] = [
        node for node in without_auth["spec"]["nodes"] if node["id"] != "sw-verify-auth"
    ]
    without_auth["spec"]["edges"] = [
        edge
        for edge in without_auth["spec"]["edges"]
        if edge["from"] != "sw-verify-auth" and edge["to"] != "sw-verify-auth"
    ]
    with pytest.raises(ValueError, match="auth"):
        assert_auth_capabilities_nonskippable(
            baseline=baseline_caps,
            proposed=required_capabilities_from_graph(without_auth),
            control_path="profile",
        )

    with pytest.raises(Exception, match="auth"):
        assert_control_path_preserves_auth(
            baseline_graph=graph,
            adjusted_graph=without_auth,
            control_path="budget",
        )
