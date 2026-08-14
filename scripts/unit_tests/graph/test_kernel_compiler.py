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

from graph.dynamic_proposal import (  # noqa: E402
    ShadowExecutorGuard,
    _strip_proposal_metric_fields,
    compare_shadow_metrics,
    compute_shadow_kernel_metrics,
    compute_verification_coverage,
    evaluate_shadow_proposal,
    run_shadow_evaluation,
)
from graph.execution_receipts import ExecutionReceiptJournal  # noqa: E402
from graph.isolation_policy import (  # noqa: E402
    classify_shadow_dispatch,
    shadow_refuse_credential_resolution,
    shadow_refuse_write_lease,
)
from graph.kernel_compiler import (  # noqa: E402
    POLICY_CLASS_IMMUTABLE,
    POLICY_CLASS_OPTIMIZABLE,
    KernelCompilationError,
    assert_policy_schema_coverage,
    classify_policy_field,
    compile_workflow_graph,
)
from graph.resource_pools import ResourcePoolRegistry  # noqa: E402
from graph.scheduler import GraphScheduler, NodeExecutionResult  # noqa: E402


def _node(
    node_id: str,
    *,
    kind: str = "command",
    strategy: str = "mechanical",
    step: str | None = None,
    write_scope: str = "worktree",
) -> dict[str, object]:
    isolation_mode = "process" if write_scope == "read-only" else "worktree"
    return {
        "id": node_id,
        "kind": kind,
        "target": {"step": step or f"sw-{node_id}"},
        "resources": {
            "pool": "code-writers",
            "slots": 1,
            "timeoutSeconds": 300,
        },
        "isolation": {"mode": isolation_mode, "writeScope": write_scope},
        "verification": {"required": True, "strategy": strategy},
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


def _shadow_graph() -> dict[str, object]:
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "shadow-fixture"},
        "spec": {
            "nodes": [
                _node("prepare"),
                _node("analysis-step", step="sw-analysis", kind="command"),
                _node("mechanical-check", kind="verifier", strategy="mechanical", write_scope="read-only"),
                _node("evidence-check", kind="verifier", strategy="evidence", write_scope="read-only"),
                _node("join-check", kind="barrier", write_scope="read-only"),
            ],
            "edges": [
                {"from": "prepare", "to": "analysis-step", "required": True},
                {"from": "analysis-step", "to": "mechanical-check", "required": True},
                {"from": "mechanical-check", "to": "evidence-check", "required": True},
                {"from": "evidence-check", "to": "join-check", "required": True},
            ],
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


def test_every_kernel_compiler_policy_field_is_classified() -> None:
    assert_policy_schema_coverage()
    assert classify_policy_field("spec.verification.required") == POLICY_CLASS_IMMUTABLE
    assert classify_policy_field("spec.resourceLimits.maxConcurrency") == (
        POLICY_CLASS_OPTIMIZABLE
    )


def test_shadow_executor_spies_off_allowlist_kinds(tmp_path: Path) -> None:
    graph = _shadow_graph()
    compiled = compile_workflow_graph(graph)
    receipts = {
        "prepare": {"tokens": 12, "durationMs": 40},
        "analysis-step": {"tokens": 50, "durationMs": 120},
    }
    executed: list[str] = []

    def inner(node: dict[str, object]) -> NodeExecutionResult:
        executed.append(str(node["id"]))
        return NodeExecutionResult(
            verdict="pass",
            output={"node": node["id"]},
            duration_ms=5,
            tokens=1,
        )

    journal = ExecutionReceiptJournal(tmp_path / "shadow")
    scheduler = GraphScheduler(
        inner,
        receipts=journal,
        pools=ResourcePoolRegistry(),
        cache_enabled=False,
    )
    result = run_shadow_evaluation(
        compiled,
        compiled,
        scheduler=scheduler,
        run_id="shadow-spy",
        receipts=receipts,
        token_cost=0.01,
    )

    assert executed == [
        "mechanical-check",
        "evidence-check",
        "join-check",
    ]
    assert "prepare" not in executed
    assert "analysis-step" not in executed
    by_id = {record.decision.node_id: record for record in result.records}
    assert by_id["prepare"].executed is False
    assert by_id["analysis-step"].executed is False
    assert by_id["mechanical-check"].executed is True


def test_mutating_analysis_node_refuses_write_lease_and_credentials() -> None:
    analysis = _node("analysis-step", step="sw-analysis", kind="command")
    assert shadow_refuse_write_lease(analysis) is True
    assert shadow_refuse_credential_resolution(analysis) is True
    decision = classify_shadow_dispatch(analysis)
    assert decision.mode == "estimate-from-receipt"


def test_shadow_predicted_versus_realized_deltas_persist(tmp_path: Path) -> None:
    graph = _shadow_graph()
    compiled = compile_workflow_graph(graph)
    receipts = {
        "prepare": {"tokens": 10, "durationMs": 100},
        "analysis-step": {"tokens": 20, "durationMs": 200},
    }
    guard = ShadowExecutorGuard(
        lambda node: NodeExecutionResult(
            verdict="pass",
            output=node["id"],
            duration_ms=7,
            tokens=3,
        ),
        receipts=receipts,
        token_cost=0.5,
    )
    for node in graph["spec"]["nodes"]:
        guard(dict(node))

    estimated = [record for record in guard.records if not record.executed]
    assert estimated
    for record in estimated:
        assert record.predicted is not None
        assert record.realized is not None
        assert record.delta_latency_ms == 0
        assert record.delta_cost == 0.0

    comparison = compare_shadow_metrics(compiled, compiled, receipts=receipts)
    assert "predictedLatencyMs" in comparison.deltas
    assert comparison.candidate.verification_coverage.aggregate > 0


def test_shadow_verification_coverage_by_verifier_class_and_aggregate() -> None:
    graph = _shadow_graph()
    compiled = compile_workflow_graph(graph)
    metrics = compute_shadow_kernel_metrics(compiled)
    coverage = metrics.verification_coverage

    assert coverage.by_verifier_class["mechanical"] == 1.0
    assert coverage.by_verifier_class["evidence"] == 1.0
    assert coverage.aggregate == pytest.approx(1.0)

    unknown_kind_graph = {
        "spec": {
            "nodes": [
                {
                    "id": "rogue",
                    "kind": "agent-generated",
                    "verification": {"required": True, "strategy": "mechanical"},
                }
            ]
        }
    }
    unknown_coverage = compute_verification_coverage(unknown_kind_graph)
    assert unknown_coverage.aggregate == 0.0
    assert unknown_coverage.by_verifier_class == {}

    proposal = deepcopy(graph)
    proposal["predictedLatencyMs"] = 1
    proposal["metrics"] = {"ignored": True}
    stripped_metrics = compute_shadow_kernel_metrics(
        compile_workflow_graph(_strip_proposal_metric_fields(proposal))
    )
    assert stripped_metrics.predicted_latency_ms != 1


def test_evaluate_shadow_proposal_end_to_end(tmp_path: Path) -> None:
    graph = _shadow_graph()
    journal = ExecutionReceiptJournal(tmp_path / "proposal-shadow")
    scheduler = GraphScheduler(
        lambda node: NodeExecutionResult(verdict="pass", output=node["id"]),
        receipts=journal,
        pools=ResourcePoolRegistry(),
        cache_enabled=False,
    )
    result = evaluate_shadow_proposal(
        graph,
        canonical_graph=graph,
        scheduler=scheduler,
        run_id="proposal-shadow",
        receipts={"prepare": {"tokens": 1, "durationMs": 2}},
    )
    payload = result.to_dict()
    assert payload["comparison"]["candidate"]["nodeCount"] == 5
    assert payload["comparison"]["deltas"]["nodeCount"] == 0
