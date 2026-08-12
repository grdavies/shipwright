#!/usr/bin/env python3
"""Safety-kernel compiler acceptance and rejection fixtures."""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.kernel_compiler import (  # noqa: E402
    KernelCompilationError,
    compile_workflow_graph,
)


def _node(node_id: str) -> dict[str, object]:
    return {
        "id": node_id,
        "kind": "command",
        "target": {"step": f"sw-{node_id}"},
        "resources": {
            "pool": "code-writers",
            "slots": 1,
            "timeoutSeconds": 300,
        },
        "isolation": {"mode": "worktree", "writeScope": "worktree"},
        "verification": {"required": True, "strategy": "mechanical"},
    }


def valid_graph() -> dict[str, object]:
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "kernel-fixture"},
        "spec": {
            "nodes": [_node("execute"), _node("verify")],
            "edges": [{"from": "execute", "to": "verify", "required": True}],
            "resourceLimits": {
                "maxConcurrency": 2,
                "maxDurationSeconds": 600,
            },
            "verification": {"required": True, "failClosed": True},
        },
    }


def test_valid_closed_catalog_graph_is_accepted() -> None:
    result = compile_workflow_graph(valid_graph())

    assert result["kernelVersion"] == "1.0.0"
    assert result["nodeKinds"] == ["command"]
    assert result["requiredGates"] == ["verification-gate"]


def test_unknown_node_kind_is_rejected() -> None:
    graph = valid_graph()
    graph["spec"]["nodes"][0]["kind"] = "agent-generated-code"

    with pytest.raises(KernelCompilationError, match="unknown node kind"):
        compile_workflow_graph(graph)


def test_undeclared_credential_and_side_effect_are_rejected() -> None:
    graph = valid_graph()

    with pytest.raises(KernelCompilationError, match="undeclared credential"):
        compile_workflow_graph(
            graph,
            node_capabilities={
                "execute": {
                    "credentials": ["github-token"],
                    "sideEffects": [],
                }
            },
        )

    with pytest.raises(KernelCompilationError, match="undeclared side effect"):
        compile_workflow_graph(
            graph,
            node_capabilities={
                "execute": {
                    "credentials": [],
                    "sideEffects": ["git-push"],
                }
            },
        )


def test_unbounded_loop_is_rejected() -> None:
    graph = valid_graph()
    graph["spec"]["nodes"][0]["kind"] = "convergence-loop"

    with pytest.raises(KernelCompilationError, match="bounded"):
        compile_workflow_graph(
            graph,
            loop_bounds={"execute": {"maxRounds": 0, "maxTokens": 100}},
        )


def test_gate_removal_or_weakening_is_rejected() -> None:
    removed = valid_graph()
    removed["spec"]["verification"]["required"] = False
    with pytest.raises(KernelCompilationError, match="verification gate"):
        compile_workflow_graph(removed)

    weakened = deepcopy(valid_graph())
    weakened["spec"]["nodes"][1]["verification"]["required"] = False
    with pytest.raises(KernelCompilationError, match="weaken"):
        compile_workflow_graph(weakened)
