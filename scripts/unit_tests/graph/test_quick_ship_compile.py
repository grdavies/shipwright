#!/usr/bin/env python3
"""Quick /sw-ship graph parity fixtures (PRD 271 R7/R8/R27)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.cutover import SafetySnapshot  # noqa: E402
from graph.execution_receipts import ExecutionReceiptJournal  # noqa: E402
from graph.kernel_compiler import compile_orchestrator_graph  # noqa: E402
from graph.quick_ship_compile import (  # noqa: E402
    GATE_STEPS,
    QUICK_SHIP_PARITY_MATRIX,
    QuickShipCompileOptions,
    VERIFIER_STEPS,
    assert_topology_fixed,
    build_quick_ship_plan,
    compile_quick_ship_graph,
    fixed_quick_ship_steps,
    parity_matrix_for_path,
    resume_step_from_ship_steps,
)
from graph.resource_pools import ResourcePoolRegistry  # noqa: E402
from graph.scheduler import GraphScheduler, NodeExecutionResult  # noqa: E402
from graph.verifier_policies import (  # noqa: E402
    VerifierKind,
    VerifierResult,
    count_independent_judgment_votes,
    evaluate_verifiers,
)
from kernel_classification import canonical_ship_chain  # noqa: E402


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _scheduler(tmp_path: Path, dispatched: list[str]) -> GraphScheduler:
    def execute(node: dict[str, object]) -> NodeExecutionResult:
        step = str(node["target"]["step"])
        dispatched.append(step)
        return NodeExecutionResult(
            verdict="pass",
            output={"step": step},
            model="fixture",
            coverage={"step": step},
        )

    return GraphScheduler(
        execute,
        receipts=ExecutionReceiptJournal(tmp_path / "receipts"),
        pools=ResourcePoolRegistry(),
    )


def test_quick_ship_compile_lifecycle_parity(tmp_path: Path) -> None:
    """R7 — fixed topology through merge-ready; never merges."""
    root = _repo_root()
    options = QuickShipCompileOptions(run_id="quick-ship-r7", phase_slug="quick-fix")
    compilation = compile_quick_ship_graph(root, options)
    kernel = compile_orchestrator_graph(compilation, proposed_steps=fixed_quick_ship_steps(root))

    graph_steps = [str(node["target"]["step"]) for node in compilation.graph["spec"]["nodes"]]
    assert graph_steps == canonical_ship_chain(root)
    assert compilation.graph["metadata"]["orchestratorType"] == "ship"
    assert compilation.source_plan["safety"]["humanMergeGate"] is True
    assert compilation.graph["spec"]["resourceLimits"]["maxConcurrency"] == 1
    assert "verification-gate" in kernel["requiredGates"]

    gate_nodes = {
        str(node["target"]["step"])
        for node in compilation.graph["spec"]["nodes"]
        if node["kind"] == "gate"
    }
    assert GATE_STEPS <= gate_nodes

    review_nodes = [
        node
        for node in compilation.graph["spec"]["nodes"]
        if str(node["target"]["step"]) in VERIFIER_STEPS
    ]
    assert review_nodes and review_nodes[0]["kind"] == "verifier"
    assert review_nodes[0]["verification"]["strategy"] == "judgment"

    safety = SafetySnapshot.from_plan(compilation.source_plan)
    assert safety.human_merge_gate is True
    dispatched: list[str] = []
    scheduler = _scheduler(tmp_path, dispatched)
    result = scheduler.run(compilation.graph, run_id=options.run_id, internal_only=True)
    assert result.verdict == "pass"
    assert "sw-ready" in dispatched


def test_quick_cutover_parity_matrix() -> None:
    """R8 — PR and no-PR paths share unconditional gates and ship-steps resume."""
    root = _repo_root()
    with_pr = build_quick_ship_plan(
        root,
        QuickShipCompileOptions(run_id="parity-pr", has_pr=True),
    )
    no_pr = build_quick_ship_plan(
        root,
        QuickShipCompileOptions(run_id="parity-nopr", has_pr=False),
    )
    assert with_pr["steps"] == no_pr["steps"]
    assert with_pr["topology"]["adaptiveSelection"] is False
    assert QUICK_SHIP_PARITY_MATRIX["resumeAuthority"] == "ship-steps.json"

    pr_path = parity_matrix_for_path(has_pr=True)
    no_pr_path = parity_matrix_for_path(has_pr=False)
    assert pr_path["merge"] == "never"
    assert no_pr_path["merge"] == "never"
    assert pr_path["verificationGate"] == "unconditional"
    assert no_pr_path["readyGate"] == "unconditional"

    chain = fixed_quick_ship_steps(root)
    resumed = resume_step_from_ship_steps({"currentStep": "sw-commit"}, chain)
    assert resumed == "sw-commit"
    assert resume_step_from_ship_steps({}, chain) == chain[0]


def test_quick_unconditional_gates_independence_floor() -> None:
    """R27/R7a — verification + ready gates unconditional; review independence floor."""
    root = _repo_root()
    compilation = compile_quick_ship_graph(
        root,
        QuickShipCompileOptions(run_id="quick-r27"),
    )
    nodes_by_step = {
        str(node["target"]["step"]): node for node in compilation.graph["spec"]["nodes"]
    }
    assert nodes_by_step["verification-gate"]["kind"] == "gate"
    assert nodes_by_step["sw-ready"]["target"].get("data", {}).get("humanMergeGate") is True

    with pytest.raises(ValueError, match="adaptive"):
        assert_topology_fixed({"adaptiveSelection": True})

    independent_review = evaluate_verifiers(
        [
            VerifierResult(
                verifier_id="sw-review",
                kind=VerifierKind.JUDGMENT,
                passed=True,
                dispatch_record={
                    "dispatch": {
                        "modelFamily": "family-a",
                        "persona": "reviewer-1",
                        "promptTemplate": "panel",
                        "contextSource": "diff",
                        "evidenceSource": "artifacts",
                    }
                },
            )
        ],
        judgment_quorum=1,
    )
    assert independent_review.passed is True
    assert count_independent_judgment_votes(independent_review.ordered_results) >= 1

    self_review = evaluate_verifiers(
        [
            VerifierResult(
                verifier_id="sw-review",
                kind=VerifierKind.JUDGMENT,
                passed=True,
                dispatch_record={
                    "dispatch": {
                        "modelFamily": "same",
                        "persona": "implementer",
                        "promptTemplate": "same",
                        "contextSource": "same",
                        "evidenceSource": "same",
                    }
                },
            ),
            VerifierResult(
                verifier_id="sw-review-duplicate",
                kind=VerifierKind.JUDGMENT,
                passed=True,
                dispatch_record={
                    "dispatch": {
                        "modelFamily": "same",
                        "persona": "implementer",
                        "promptTemplate": "same",
                        "contextSource": "same",
                        "evidenceSource": "same",
                    }
                },
            ),
        ],
        judgment_quorum=2,
    )
    assert self_review.passed is False
