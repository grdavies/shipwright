#!/usr/bin/env python3
"""Scheduler-dependent graph capability fixtures."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.artifact_registry import ArtifactRegistry  # noqa: E402
from graph.cost_telemetry import next_model_tier, telemetry_from_receipt  # noqa: E402
from graph.legacy_adapters import (  # noqa: E402
    compile_legacy_plan,
    restore_legacy_plan,
)
from graph.router_nodes import (  # noqa: E402
    RouteDecision,
    RouteDecisionJournal,
    hash_route_input,
)
from graph.scheduling_modes import (  # noqa: E402
    ScheduledItem,
    SchedulingMode,
    measure_schedule,
    validate_scheduling_mode,
)
from graph.typed_dataflow import (  # noqa: E402
    DataflowError,
    TypedEdge,
    build_dispatch_context,
    unnecessary_edge_report,
)
from graph.verifier_policies import (  # noqa: E402
    VerifierKind,
    VerifierResult,
    evaluate_verifiers,
)


def test_pipeline_and_barrier_metrics() -> None:
    metrics = measure_schedule(
        [
            ScheduledItem("a", 0, 10),
            ScheduledItem("b", 0, 10),
            ScheduledItem("join", 10, 12, mode=SchedulingMode.BARRIER),
        ],
        available_slots=2,
    )
    assert metrics.serial_baseline_ms == 22
    assert metrics.elapsed_ms == 12
    assert metrics.speedup > 1
    assert 0 < metrics.slot_utilization <= 1
    assert metrics.barrier_idle_ms == 4
    with pytest.raises(ValueError, match="barrier nodes"):
        validate_scheduling_mode("barrier", "pipeline")


def test_typed_dataflow_dispatches_least_context_and_reports_advisory(
    tmp_path: Path,
) -> None:
    registry = ArtifactRegistry(tmp_path / "artifacts")
    registry.register(
        artifact_id="input",
        content={"needed": {"value": 7}, "secret": "not-selected"},
        schema="example/v1",
        producing_node="producer",
        input_revision="abc",
        verification_evidence=[],
    )
    edges = [
        TypedEdge("needed", "producer", "consumer", "input", "example/v1", "/needed"),
        TypedEdge(
            "optional",
            "producer",
            "consumer",
            "missing",
            "example/v1",
            required=False,
        ),
    ]
    context = build_dispatch_context("consumer", edges, registry)
    assert context.inputs == {"needed": {"value": 7}}
    assert "secret" not in repr(context.inputs)
    assert unnecessary_edge_report(edges, {"needed"})[0]["edgeId"] == "optional"
    assert len(edges) == 2

    with pytest.raises(DataflowError, match="required artifact"):
        build_dispatch_context(
            "consumer",
            [TypedEdge("gap", "producer", "consumer", "missing", "example/v1")],
            registry,
        )


def test_mechanical_failure_overrides_passing_judgment_quorum() -> None:
    verdict = evaluate_verifiers(
        [
            VerifierResult("tests", VerifierKind.MECHANICAL, False),
            VerifierResult("review-a", VerifierKind.JUDGMENT, True),
            VerifierResult("review-b", VerifierKind.JUDGMENT, True),
        ],
        judgment_quorum=2,
    )
    assert verdict.passed is False
    assert verdict.decisive_kind is VerifierKind.MECHANICAL


def test_telemetry_and_escalation_stay_allowlist_bound() -> None:
    telemetry = telemetry_from_receipt(
        {
            "nodeId": "build",
            "tokens": 100,
            "durationMs": 20,
            "attempts": 2,
            "verdict": "pass",
            "coverage": {"verificationSurvived": True},
        },
        token_cost=0.001,
    )
    assert telemetry.retries == 1
    assert telemetry.cost_per_accepted_result == pytest.approx(0.1)
    assert next_model_tier(
        "cheap", {"low-confidence"}, allowed_tiers={"cheap", "build", "mid", "deep"}, tiers={
            "cheap": "c", "build": "b", "mid": "m", "deep": "d",
        }
    ) == "build"
    assert next_model_tier(
        "build", {"low-confidence"}, allowed_tiers={"cheap", "build", "mid", "deep"}, tiers={
            "cheap": "c", "build": "b", "mid": "m", "deep": "d",
        }
    ) == "mid"
    assert next_model_tier(
        "build", {"verifier-disagreement"}, allowed_tiers={"cheap", "build", "mid", "deep"}, tiers={
            "cheap": "c", "build": "b", "mid": "m", "deep": "d",
        }
    ) == "deep"
    with pytest.raises(PermissionError):
        next_model_tier(
            "build", {"schema-failure"}, allowed_tiers={"cheap", "build", "mid"}, tiers={
                "cheap": "c", "build": "b", "mid": "m", "deep": "d",
            }
        )


def test_router_decision_is_durable_and_complete(tmp_path: Path) -> None:
    journal = RouteDecisionJournal(tmp_path / "routes")
    decision = RouteDecision(
        router_id="triage",
        input_hash=hash_route_input({"signal": "failure"}),
        selected_route="debug",
        rule_version="2",
        classifier_model="fixture-model",
        confidence=0.72,
        overrides=("human-confirmed",),
    )
    event = journal.record("event-1", decision)
    assert event == journal.read("event-1")
    assert set(event) >= {
        "inputHash",
        "selectedRoute",
        "ruleVersion",
        "classifierModel",
        "confidence",
        "overrides",
    }


@pytest.mark.parametrize(
    ("plan_type", "plan"),
    [
        (
            "delivery",
            {
                "version": 1,
                "phases": [{"id": "one", "slug": "prepare"}, {"id": "two", "slug": "ship"}],
                "contention": {"serialize": ["one", "two"]},
                "kernelFloor": ["verification-gate"],
            },
        ),
        (
            "execute",
            {
                "version": 1,
                "steps": ["plan-self-review", "tdd-gate", "refactor-gate"],
                "kernelFloor": ["tdd-gate"],
            },
        ),
        (
            "ship",
            {
                "version": 1,
                "steps": [{"id": "verify", "command": "sw-verify"}, "sw-ready"],
                "contention": {"paths": ["status.json"]},
            },
        ),
    ],
)
def test_legacy_adapter_round_trip_preserves_kernel_and_contention(
    plan_type: str, plan: dict[str, object]
) -> None:
    compiled = compile_legacy_plan(plan, plan_type=plan_type)
    assert compiled.graph["kind"] == "WorkflowGraph"
    assert restore_legacy_plan(compiled) == plan
