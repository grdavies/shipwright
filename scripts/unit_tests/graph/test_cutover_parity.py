#!/usr/bin/env python3
"""Cutover parity and per-orchestrator R3 contract fixtures."""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.cutover import (  # noqa: E402
    CoverageLossError,
    CutoverDriver,
    CutoverStage,
    DogfoodEvidence,
    SafetySnapshot,
)
from graph.execution_receipts import ExecutionReceiptJournal  # noqa: E402
from graph.kernel_compiler import (  # noqa: E402
    KernelCompilationError,
    compile_and_dispatch,
    compile_orchestrator_graph,
    compile_workflow_graph,
    dispatch_compiled_graph,
    resolve_graph_run_id,
)
from graph.legacy_adapters import (  # noqa: E402
    ORCHESTRATOR_CONTRACTS,
    compile_legacy_plan,
    orchestrator_plan_to_workflow_graph,
)
from graph.resource_pools import ResourcePoolRegistry  # noqa: E402
from graph.scheduler import GraphScheduler, NodeExecutionResult  # noqa: E402

ORCHESTRATOR_SUITE = ("delivery", "doc", "debug", "feedback")


def _deliver_plan() -> dict[str, object]:
    return {
        "version": 1,
        "runId": "deliver-run-1",
        "phases": [
            {"id": "prepare", "slug": "prepare"},
            {"id": "verify", "slug": "verify"},
            {"id": "ready", "slug": "ready"},
        ],
        "safety": {
            "lockOwner": "deliver-run-1",
            "mergeQueue": ["prepare", "verify"],
            "contentionSerialized": ["shared-state"],
            "resumeCursor": "verify",
            "humanMergeGate": True,
        },
    }


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


def test_non_critical_deliver_cutover_matches_legacy_safety_and_coverage(
    tmp_path: Path,
) -> None:
    plan = _deliver_plan()
    safety = SafetySnapshot.from_plan(plan)
    legacy_dispatched: list[str] = []
    legacy = CutoverDriver.run_legacy(
        plan,
        plan_type="delivery",
        safety=safety,
        executor=lambda step: legacy_dispatched.append(step) or "pass",
    )
    dispatched: list[str] = []
    driver = CutoverDriver(stage=CutoverStage.DOGFOOD)

    cutover = driver.run_scheduler(
        plan,
        plan_type="delivery",
        run_id="dogfood-deliver",
        scheduler=_scheduler(tmp_path, dispatched),
        safety=safety,
        non_merge_critical=True,
    )

    parity = driver.compare(legacy, cutover)
    assert parity.passed is True
    assert parity.coverage_complete is True
    assert parity.safety_unchanged is True
    assert cutover.safety.lock_owner == "deliver-run-1"
    assert cutover.safety.merge_queue == ("prepare", "verify")
    assert cutover.safety.contention_serialized == ("shared-state",)
    assert cutover.safety.resume_cursor == "verify"
    assert cutover.safety.human_merge_gate is True
    assert legacy_dispatched == ["prepare", "verify", "ready"]
    assert dispatched == ["prepare", "verify", "ready"]


def test_phased_promotion_requires_dogfood_parity_and_coverage() -> None:
    driver = CutoverDriver(stage=CutoverStage.DOGFOOD)
    with pytest.raises(PermissionError, match="dogfood gate"):
        driver.promote(
            DogfoodEvidence(
                completed_runs=1,
                parity_passed=False,
                coverage_complete=True,
                verification_passed=True,
            )
        )

    assert driver.promote(DogfoodEvidence.passing(completed_runs=1)) is CutoverStage.LIMITED
    assert driver.promote(DogfoodEvidence.passing(completed_runs=3)) is CutoverStage.FULL


@pytest.mark.parametrize(
    ("plan_type", "plan"),
    [
        ("delivery", {"phases": [{"id": "one", "slug": "deliver-one"}]}),
        ("execute", {"steps": ["plan-self-review", "tdd-gate"]}),
        ("ship", {"steps": ["sw-verify", "sw-ready"]}),
    ],
)
def test_full_ownership_supports_each_legacy_plan_type(
    tmp_path: Path,
    plan_type: str,
    plan: dict[str, object],
) -> None:
    safety = SafetySnapshot("run", (), (), "start", True)
    legacy = CutoverDriver.run_legacy(
        plan,
        plan_type=plan_type,
        safety=safety,
        executor=lambda _step: "pass",
    )
    cutover = CutoverDriver(stage=CutoverStage.FULL).run_scheduler(
        plan,
        plan_type=plan_type,
        run_id=f"full-{plan_type}",
        scheduler=_scheduler(tmp_path, []),
        safety=safety,
    )
    assert CutoverDriver.compare(legacy, cutover).passed is True


def test_intentionally_dropped_node_fails_closed_before_dispatch(
    tmp_path: Path,
) -> None:
    dispatched: list[str] = []
    driver = CutoverDriver(stage=CutoverStage.DOGFOOD)

    def drop_verify(graph: dict[str, object]) -> dict[str, object]:
        damaged = deepcopy(graph)
        damaged["spec"]["nodes"] = [
            node for node in damaged["spec"]["nodes"] if node["target"]["step"] != "verify"
        ]
        damaged["spec"]["edges"] = [
            edge
            for edge in damaged["spec"]["edges"]
            if "verify" not in edge["from"] and "verify" not in edge["to"]
        ]
        return damaged

    with pytest.raises(CoverageLossError, match="coverage loss"):
        driver.run_scheduler(
            _deliver_plan(),
            plan_type="delivery",
            run_id="coverage-loss",
            scheduler=_scheduler(tmp_path, dispatched),
            safety=SafetySnapshot.from_plan(_deliver_plan()),
            non_merge_critical=True,
            graph_transform=drop_verify,
        )

    assert dispatched == []


def test_empty_plan_fails_closed() -> None:
    with pytest.raises(ValueError, match="at least one step|no supported steps"):
        compile_legacy_plan({"phases": []}, plan_type="delivery")


def test_one_step_plan_compiles_with_no_edges() -> None:
    compiled = orchestrator_plan_to_workflow_graph(
        {"steps": ["normalize"], "runId": "doc-one", "orchestratorType": "doc"},
        orchestrator_type="doc",
    )
    assert len(compiled.graph["spec"]["nodes"]) == 1
    assert compiled.graph["spec"]["edges"] == []
    assert compiled.run_id == "doc-one"


def test_parallel_waves_keep_real_edges_not_serial_siblings() -> None:
    plan = {
        "runId": "deliver-f73930bc36de4aeba1bcfef3573b90a8",
        "phases": [
            {"id": "a", "slug": "alpha"},
            {"id": "b", "slug": "bravo"},
            {"id": "c", "slug": "charlie"},
        ],
        "waves": [["a", "b"], ["c"]],
        "edges": [
            {"from": "a", "to": "c"},
            {"from": "b", "to": "c"},
        ],
    }
    compiled = compile_legacy_plan(plan, plan_type="delivery")
    edge_pairs = {(edge["from"], edge["to"]) for edge in compiled.graph["spec"]["edges"]}
    node_by_step = {
        node["target"]["step"]: node["id"] for node in compiled.graph["spec"]["nodes"]
    }
    assert (node_by_step["alpha"], node_by_step["charlie"]) in edge_pairs
    assert (node_by_step["bravo"], node_by_step["charlie"]) in edge_pairs
    assert (node_by_step["alpha"], node_by_step["bravo"]) not in edge_pairs
    assert (node_by_step["bravo"], node_by_step["alpha"]) not in edge_pairs
    assert compiled.run_id == "deliver-f73930bc36de4aeba1bcfef3573b90a8"
    assert compiled.graph["spec"]["resourceLimits"]["maxConcurrency"] >= 2


def test_deliver_run_id_maps_to_graph_run_id() -> None:
    compiled = compile_legacy_plan(
        {"phases": [{"id": "p1", "slug": "one"}], "runId": "deliver-xyz"},
        plan_type="delivery",
    )
    assert compiled.run_id == "deliver-xyz"
    assert compiled.graph["metadata"]["runId"] == "deliver-xyz"
    assert (
        resolve_graph_run_id(compiled.graph, fallback_run_id="ignored") == "deliver-xyz"
    )


def test_kernel_is_only_scheduler_admission_path(tmp_path: Path) -> None:
    plan = {
        "steps": ["memory-prework", "normalize"],
        "orchestratorType": "feedback",
        "runId": "graph-feedback-1",
        "data": {"signal": {"text": "user feedback"}},
    }
    compiled_plan = orchestrator_plan_to_workflow_graph(
        plan, orchestrator_type="feedback"
    )
    kernel = compile_orchestrator_graph(compiled_plan)
    assert kernel["graphHash"]
    assert kernel["kernelVersion"]
    assert kernel["dataPayloads"]["data"] == {"signal": {"text": "user feedback"}}
    assert "verification-gate" in kernel["safetyKernelCalls"]

    dispatched: list[str] = []
    scheduler = _scheduler(tmp_path, dispatched)
    result = dispatch_compiled_graph(
        kernel,
        scheduler=scheduler,
        run_id=compiled_plan.run_id,
        internal_only=True,
    )
    assert result.verdict == "pass"
    assert dispatched == ["memory-prework", "normalize"]

    with pytest.raises(KernelCompilationError, match="kernel-compiled artifact"):
        dispatch_compiled_graph(
            {"graph": compiled_plan.graph},
            scheduler=scheduler,
            run_id="bypass",
        )


def test_untrusted_debug_feedback_payloads_cannot_set_security_or_structure() -> None:
    with pytest.raises(KernelCompilationError, match="graph structure"):
        compile_orchestrator_graph(
            orchestrator_plan_to_workflow_graph(
                {
                    "steps": ["triage"],
                    "orchestratorType": "debug",
                    "nodes": [{"id": "evil"}],
                },
                orchestrator_type="debug",
            )
        )
    with pytest.raises(KernelCompilationError, match="security field"):
        compile_workflow_graph(
            orchestrator_plan_to_workflow_graph(
                {
                    "steps": ["normalize"],
                    "orchestratorType": "feedback",
                    "runId": "graph-feedback-ok",
                },
                orchestrator_type="feedback",
            ).graph,
            orchestrator="feedback",
            data_payloads={"evil": {"humanMergeGate": False}},
        )


@pytest.mark.parametrize("orchestrator", ORCHESTRATOR_SUITE)
def test_per_orchestrator_halt_confirmation_redaction_dispatch_contracts(
    tmp_path: Path,
    orchestrator: str,
) -> None:
    """Each orchestrator suite asserts halt, token, redaction, dispatch, durability, kernel."""
    expected = ORCHESTRATOR_CONTRACTS[orchestrator]
    if orchestrator == "delivery":
        plan: dict[str, object] = {
            "runId": "deliver-contract",
            "phases": [
                {"id": "prepare", "slug": "prepare"},
                {"id": "ready", "slug": "ready"},
            ],
            "edges": [{"from": "prepare", "to": "ready"}],
        }
        compiled = compile_legacy_plan(plan, plan_type="delivery")
    else:
        steps = {
            "doc": ["memory-prework", "prd", "afterTasks-checkpoint"],
            "debug": ["memory-prework", "triage", "route-confirm-halt"],
            "feedback": ["memory-prework", "redact", "human-confirm-halt"],
        }[orchestrator]
        plan = {
            "steps": steps,
            "orchestratorType": orchestrator,
            "runId": f"graph-{orchestrator}-contract",
            "data": {"note": "payload-only"}
            if orchestrator in {"debug", "feedback"}
            else {},
        }
        compiled = orchestrator_plan_to_workflow_graph(
            plan, orchestrator_type=orchestrator
        )

    contracts = compiled.contracts
    assert contracts["humanHalt"] == expected["humanHalt"]
    assert contracts["confirmationToken"] == expected["confirmationToken"]
    assert contracts["redactionBoundary"] == expected["redactionBoundary"]
    assert contracts["dispatchBoundary"] == expected["dispatchBoundary"]
    assert contracts["durabilityRule"] == expected["durabilityRule"]
    assert tuple(contracts["safetyKernelCalls"]) == expected["safetyKernelCalls"]

    kernel = compile_orchestrator_graph(compiled)
    assert "verification-gate" in kernel["requiredGates"]
    assert kernel["orchestrator"] == orchestrator
    assert compiled.run_id
    crash_replay_key = f"{compiled.run_id}:{kernel['graphHash']}"
    assert crash_replay_key.startswith(compiled.run_id)

    dispatched: list[str] = []
    _, run = compile_and_dispatch(
        compiled.graph,
        scheduler=_scheduler(tmp_path / orchestrator, dispatched),
        run_id=compiled.run_id,
        internal_only=True,
        kernel_options={
            "orchestrator": orchestrator,
            "data_payloads": compiled.untrusted_payload,
        },
    )
    assert run.verdict == "pass"
    assert dispatched
    assert len(dispatched) == len(compiled.graph["spec"]["nodes"])
