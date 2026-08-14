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
from graph.cutover import (  # noqa: E402
    CutoverDriver,
    CutoverStage,
    DogfoodEvidence,
    SafetySnapshot,
)
from graph.dynamic_proposal import (  # noqa: E402
    ProposalBudget,
    admit_host_slot_candidates,
    evaluate_dynamic_proposal,
)
from graph.execution_receipts import ExecutionReceiptJournal  # noqa: E402
from graph.ir import validate_workflow_graph  # noqa: E402
from graph.resource_pools import PoolExhausted, ResourcePoolRegistry  # noqa: E402
from graph.scheduler import GraphScheduler, NodeExecutionResult  # noqa: E402
from graph.scheduling_modes import (  # noqa: E402
    ExternalDispatchAuthorization,
    MitigationLane,
    PromotionMetrics,
    RegressionBudget,
    SERIAL_EQUIVALENT_MAX_CONCURRENCY,
    ScheduledItem,
    authorize_external_dispatch,
    is_serial_equivalent,
    serial_equivalent_metrics,
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


def _budget(*, max_nodes: int = 4, max_edges: int = 4, max_total_slots: int = 4) -> ProposalBudget:
    return ProposalBudget(
        max_nodes=max_nodes,
        max_edges=max_edges,
        max_concurrency=4,
        max_duration_seconds=300,
        max_total_slots=max_total_slots,
    )


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
        "metadata": {"name": "required-capability-fixture"},
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
        "budget": _budget(max_nodes=8, max_edges=8, max_total_slots=8),
    }


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
    assert fallback.graph == validate_workflow_graph(canonical)
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


def _dogfood_plan() -> dict[str, Any]:
    return {
        "version": 1,
        "runId": "dogfood-stress",
        "phases": [
            {"id": "prepare", "slug": "prepare"},
            {"id": "verify", "slug": "verify"},
        ],
        "safety": {
            "lockOwner": "dogfood-stress",
            "mergeQueue": ["prepare"],
            "contentionSerialized": ["shared-state"],
            "resumeCursor": "verify",
            "humanMergeGate": True,
        },
    }


def _promotion_budget() -> RegressionBudget:
    return RegressionBudget(
        wall_clock_ms=5_000,
        cache_hit_rate_min=0.0,
        max_cost=10.0,
        max_failures=1,
        max_retries=2,
        scheduler_overhead_ms=500,
    )


def _metrics_from_run(
    *,
    wall_clock_ms: int,
    cache_hits: int,
    total_nodes: int,
    total_cost: float,
    failures: int,
    retries: int,
    scheduler_overhead_ms: int,
) -> PromotionMetrics:
    hit_rate = (cache_hits / total_nodes) if total_nodes else 0.0
    return PromotionMetrics(
        wall_clock_ms=wall_clock_ms,
        cache_hit_rate=hit_rate,
        total_cost=total_cost,
        failure_count=failures,
        retry_count=retries,
        scheduler_overhead_ms=scheduler_overhead_ms,
    )


def test_promotion_evidence_records_metrics_within_budget() -> None:
    metrics = _metrics_from_run(
        wall_clock_ms=1200,
        cache_hits=1,
        total_nodes=3,
        total_cost=0.42,
        failures=0,
        retries=1,
        scheduler_overhead_ms=80,
    )
    budget = _promotion_budget()
    assert metrics.within_budget(budget) is True

    driver = CutoverDriver(stage=CutoverStage.DOGFOOD)
    driver.promote(DogfoodEvidence.passing(completed_runs=1), metrics=metrics)
    assert driver.promotion_evidence[-1].metrics == metrics
    driver.promote(
        DogfoodEvidence.passing(completed_runs=3),
        metrics=metrics,
        authorizer="graph-runtime-cutover",
        evidence_ref="wave-h-promotion",
    )
    assert driver.stage is CutoverStage.FULL
    assert driver.promotion_evidence[-1].evidence_ref == "wave-h-promotion"


def test_serial_equivalent_mode_and_cache_disable_without_legacy_adapter(
    tmp_path: Path,
) -> None:
    lane = MitigationLane(cache_enabled=False)
    assert is_serial_equivalent(lane.max_concurrency)
    assert lane.max_concurrency == SERIAL_EQUIVALENT_MAX_CONCURRENCY

    graph = _graph()
    graph["spec"]["resourceLimits"]["maxConcurrency"] = lane.max_concurrency
    calls: list[str] = []

    def execute(node: dict[str, Any]) -> NodeExecutionResult:
        calls.append(str(node["id"]))
        return NodeExecutionResult(
            verdict="pass",
            output={"node": node["id"]},
            model="fixture",
            duration_ms=5,
            tokens=10,
        )

    scheduler = GraphScheduler(
        execute,
        receipts=ExecutionReceiptJournal(tmp_path / "serial"),
        pools=ResourcePoolRegistry(),
        cache_enabled=lane.cache_enabled,
    )
    first = scheduler.run(graph, run_id="serial-a", internal_only=True)
    second = scheduler.run(graph, run_id="serial-b", internal_only=True)
    assert first.verdict == "pass"
    assert second.verdict == "pass"
    assert calls == ["prepare", "prepare"]

    metrics = serial_equivalent_metrics(
        [
            ScheduledItem("prepare", 0, 5),
            ScheduledItem("prepare", 5, 10),
        ]
    )
    assert metrics.elapsed_ms == metrics.serial_baseline_ms


def test_leaving_internal_only_requires_named_authorizer(tmp_path: Path) -> None:
    graph = _graph()
    journal = ExecutionReceiptJournal(tmp_path / "receipts")
    scheduler = GraphScheduler(
        lambda node: NodeExecutionResult(verdict="pass", output=node["id"]),
        receipts=journal,
        pools=ResourcePoolRegistry(),
    )
    with pytest.raises(PermissionError, match="authorizer"):
        scheduler.run(graph, run_id="external", internal_only=False)
    auth = authorize_external_dispatch(
        ExternalDispatchAuthorization(
            authorizer="cutover-full-ownership-gate",
            evidence_ref="wave-h-external",
        )
    )
    result = scheduler.run(
        graph,
        run_id="external",
        internal_only=False,
        external_authorization=auth,
    )
    assert result.verdict == "pass"


def test_dogfood_pool_exhaustion_write_contention_and_cancel(tmp_path: Path) -> None:
    plan = _dogfood_plan()
    safety = SafetySnapshot.from_plan(plan)
    graph = {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "dogfood-stress"},
        "spec": {
            "nodes": [
                {
                    "id": "prepare",
                    "kind": "command",
                    "target": {"step": "prepare"},
                    "resources": {"pool": "code-writers", "slots": 1, "timeoutSeconds": 30},
                    "isolation": {"mode": "process", "writeScope": "scoped"},
                    "verification": {"required": True, "strategy": "mechanical"},
                },
                {
                    "id": "verify",
                    "kind": "command",
                    "target": {"step": "verify"},
                    "resources": {"pool": "code-writers", "slots": 1, "timeoutSeconds": 30},
                    "isolation": {"mode": "process", "writeScope": "scoped"},
                    "verification": {"required": True, "strategy": "mechanical"},
                },
            ],
            "edges": [{"from": "prepare", "to": "verify", "required": True}],
            "resourceLimits": {
                "maxConcurrency": SERIAL_EQUIVALENT_MAX_CONCURRENCY,
                "maxDurationSeconds": 120,
            },
            "verification": {"required": True, "failClosed": True},
        },
    }

    # Pool exhaustion: second acquire blocks until first releases.
    pools = ResourcePoolRegistry.from_config(limits={"code-writers": 1})
    from graph.resource_pools import PoolName

    pools.acquire(PoolName.CODE_WRITERS, slots=1)
    with pytest.raises(PoolExhausted):
        pools.acquire(PoolName.CODE_WRITERS, slots=1)

    order: list[str] = []

    def execute(node: dict[str, Any]) -> NodeExecutionResult:
        order.append(str(node["id"]))
        return NodeExecutionResult(verdict="pass", output=node["id"])

    shared_write = GraphScheduler(
        execute,
        receipts=ExecutionReceiptJournal(tmp_path / "contention"),
        pools=ResourcePoolRegistry.from_config(limits={"code-writers": 4}),
    ).run(
        graph,
        run_id="contention",
        internal_only=True,
        write_paths={"prepare": {"shared/out.json"}, "verify": {"shared/out.json"}},
    )
    assert shared_write.verdict == "pass"
    assert order == ["prepare", "verify"]
    assert shared_write.contention_findings

    cancelled: list[str] = []

    def fail_then_cancel(node: dict[str, Any]) -> NodeExecutionResult:
        node_id = str(node["id"])
        cancelled.append(node_id)
        if node_id == "prepare":
            cancel_scheduler.request_cancel()
        return NodeExecutionResult(verdict="pass", output=node_id)

    cancel_scheduler = GraphScheduler(
        fail_then_cancel,
        receipts=ExecutionReceiptJournal(tmp_path / "cancel"),
        pools=ResourcePoolRegistry(),
    )
    cancel_result = cancel_scheduler.run(graph, run_id="cancel", internal_only=True)
    assert cancel_result.verdict == "fail"
    assert "prepare" in cancelled
    by_id = {item.node_id: item for item in cancel_result.nodes}
    assert by_id["verify"].verdict == "cancelled"

    driver = CutoverDriver(stage=CutoverStage.DOGFOOD)
    legacy = CutoverDriver.run_legacy(
        plan,
        plan_type="delivery",
        safety=safety,
        executor=lambda _step: "pass",
    )
    cutover = driver.run_scheduler(
        plan,
        plan_type="delivery",
        run_id="dogfood-stress",
        scheduler=GraphScheduler(
            lambda node: NodeExecutionResult(verdict="pass", output=node["id"]),
            receipts=ExecutionReceiptJournal(tmp_path / "dogfood"),
            pools=ResourcePoolRegistry(),
        ),
        safety=safety,
        non_merge_critical=True,
    )
    assert CutoverDriver.compare(legacy, cutover).passed is True


def test_merge_gate_deletion_and_ceiling_bust_rejected_before_shadow() -> None:
    canonical = _required_capability_graph()
    kwargs = _green_proposal_kwargs()

    deleted = deepcopy(canonical)
    deleted["spec"]["nodes"] = [
        node for node in deleted["spec"]["nodes"] if node["id"] != "merge-gate"
    ]
    deleted["spec"]["edges"] = [
        edge
        for edge in deleted["spec"]["edges"]
        if edge["from"] != "merge-gate" and edge["to"] != "merge-gate"
    ]
    deleted["spec"]["edges"].append(
        {"from": "mechanical-verification", "to": "credential-broker", "required": True}
    )

    deleted_decision = evaluate_dynamic_proposal(
        deleted,
        canonical_graph=canonical,
        **kwargs,
    )
    assert deleted_decision.verdict == "canonical-fallback"
    assert deleted_decision.used_fallback is True
    assert "merge-gate" in deleted_decision.reason or "required-capability" in deleted_decision.reason

    lowered = deepcopy(canonical)
    for node in lowered["spec"]["nodes"]:
        if node["id"] == "merge-gate":
            node["verification"]["required"] = False
    lowered_decision = evaluate_dynamic_proposal(
        lowered,
        canonical_graph=canonical,
        **kwargs,
    )
    assert lowered_decision.used_fallback is True

    bust = deepcopy(canonical)
    bust["spec"]["resourceLimits"]["maxConcurrency"] = 3
    bust_decision = evaluate_dynamic_proposal(
        bust,
        canonical_graph=canonical,
        **kwargs,
    )
    assert bust_decision.verdict == "canonical-fallback"
    assert bust_decision.used_fallback is True
    assert "concurrency" in bust_decision.reason or "ceiling" in bust_decision.reason


def test_required_capability_nodes_stay_byte_identical_and_host_slots_cannot_rise() -> None:
    canonical = _required_capability_graph()
    kwargs = _green_proposal_kwargs()

    mutated_lease = deepcopy(canonical)
    for node in mutated_lease["spec"]["nodes"]:
        if node["id"] == "write-isolation-lease":
            node["resources"]["timeoutSeconds"] = 99
    lease_decision = evaluate_dynamic_proposal(
        mutated_lease,
        canonical_graph=canonical,
        **kwargs,
    )
    assert lease_decision.used_fallback is True
    assert "byte-identical" in lease_decision.reason or "required-capability" in lease_decision.reason

    risen = deepcopy(canonical)
    risen["spec"]["nodes"][0]["resources"]["slots"] = 2
    risen_decision = evaluate_dynamic_proposal(
        risen,
        canonical_graph=canonical,
        **kwargs,
    )
    assert risen_decision.used_fallback is True
    assert "slot" in risen_decision.reason

    ceiling = 5
    first = deepcopy(canonical)
    second = deepcopy(canonical)
    second["spec"]["nodes"][0]["target"] = {"step": "sw-prepare-alt"}
    verdicts = admit_host_slot_candidates(
        [first, second],
        host_slot_ceiling=ceiling,
    )
    assert verdicts == ["admitted", "queued"]

    oversize = deepcopy(canonical)
    for node in oversize["spec"]["nodes"]:
        node["resources"]["slots"] = 4
    rejected = admit_host_slot_candidates(
        [oversize],
        host_slot_ceiling=ceiling,
    )
    assert rejected == ["rejected"]
