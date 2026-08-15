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
    HIGH_REGRET_THRESHOLD,
    MIN_CALIBRATION_SAMPLE,
    ROUTE_DETERMINISTIC_TRIAGE,
    ROUTE_FULL_WORKFLOW,
    ROUTE_QUICK,
    RouteCalibrationSample,
    RouteCalibrationTable,
    RouteDecision,
    RouteDecisionJournal,
    RouteRunOutcome,
    compute_routing_regret,
    deterministic_route_for_class,
    hash_route_input,
    normalize_files_changed,
    record_routing_regret,
    select_calibrated_route,
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
    count_independent_judgment_votes,
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
        schema="example@1",
        producing_node="producer",
        input_revision="abc",
        verification_evidence=[],
    )
    edges = [
        TypedEdge("needed", "producer", "consumer", "input", "example@1", "/needed"),
        TypedEdge(
            "optional",
            "producer",
            "consumer",
            "missing",
            "example@1",
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
            [TypedEdge("gap", "producer", "consumer", "missing", "example@1")],
            registry,
        )


def test_mechanical_failure_overrides_passing_judgment_quorum() -> None:
    verdict = evaluate_verifiers(
        [
            VerifierResult("tests", VerifierKind.MECHANICAL, False),
            VerifierResult(
                "review-a",
                VerifierKind.JUDGMENT,
                True,
                dispatch_record={
                    "dispatch": {
                        "modelFamily": "family-a",
                        "persona": "security",
                        "promptTemplate": "review-v1",
                        "contextSource": "diff",
                        "evidenceSource": "receipt",
                    }
                },
            ),
            VerifierResult(
                "review-b",
                VerifierKind.JUDGMENT,
                True,
                dispatch_record={
                    "dispatch": {
                        "modelFamily": "family-b",
                        "persona": "design",
                        "promptTemplate": "review-v2",
                        "contextSource": "plan",
                        "evidenceSource": "artifact",
                    }
                },
            ),
        ],
        judgment_quorum=2,
    )
    assert verdict.passed is False
    assert verdict.decisive_kind is VerifierKind.MECHANICAL


def _judgment_dispatch(
    *,
    model_family: str = "gpt",
    persona: str = "security",
    prompt_template: str = "review-v1",
    context_source: str = "diff",
    evidence_source: str = "receipt",
) -> dict[str, object]:
    return {
        "dispatch": {
            "modelFamily": model_family,
            "persona": persona,
            "promptTemplate": prompt_template,
            "contextSource": context_source,
            "evidenceSource": evidence_source,
        }
    }


def test_correlated_judgment_votes_fail_quorum_at_two() -> None:
    shared = _judgment_dispatch()
    results = [
        VerifierResult(
            f"review-{index}",
            VerifierKind.JUDGMENT,
            True,
            dispatch_record=shared,
        )
        for index in range(3)
    ]
    assert count_independent_judgment_votes(results, passed_only=True) == 1
    verdict = evaluate_verifiers(results, judgment_quorum=2)
    assert verdict.passed is False
    assert verdict.decisive_kind is VerifierKind.JUDGMENT
    assert verdict.reason == "judgment quorum not reached"


def test_self_declared_prompt_does_not_create_independence() -> None:
    recorded = _judgment_dispatch()
    results = [
        VerifierResult(
            "review-a",
            VerifierKind.JUDGMENT,
            True,
            dispatch_record={
                **recorded,
                "payload": {"promptTemplate": "self-declared-a"},
            },
        ),
        VerifierResult(
            "review-b",
            VerifierKind.JUDGMENT,
            True,
            dispatch_record={
                **recorded,
                "payload": {"promptTemplate": "self-declared-b"},
            },
        ),
    ]
    assert count_independent_judgment_votes(results, passed_only=True) == 1


def test_zero_judgment_verifiers_fail_when_quorum_required() -> None:
    verdict = evaluate_verifiers([], judgment_quorum=1)
    assert verdict.passed is False
    assert verdict.decisive_kind is VerifierKind.JUDGMENT
    assert verdict.reason == "judgment quorum not reached"


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


def test_over_routed_quick_records_high_regret_and_below_sample_buckets_hold_route() -> None:
    scope = ("scripts/graph/router_nodes.py",)
    outcome = RouteRunOutcome(
        ready_without_rework=False,
        workflow_depth=ROUTE_FULL_WORKFLOW,
        retries=3,
        cost=12.5,
        declared_scope=scope,
        files_changed=(
            "scripts/graph/router_nodes.py",
            "README.md",
        ),
    )
    assert normalize_files_changed(outcome.files_changed, scope) == (
        "scripts/graph/router_nodes.py",
    )

    decision = RouteDecision(
        router_id="routing",
        input_hash=hash_route_input({"signal": "small-fix"}),
        selected_route=ROUTE_QUICK,
        rule_version="1",
        classifier_model="cheap-model",
        confidence=0.96,
    )
    regret = compute_routing_regret(
        decision.selected_route,
        outcome,
        confidence=decision.confidence,
    )
    assert regret >= HIGH_REGRET_THRESHOLD

    regretted = record_routing_regret(decision, outcome)
    assert regretted.routing_regret == regret

    allowed = {"cheap", "build", "mid", "deep"}
    tiers = {"cheap": "c", "build": "b", "mid": "m", "deep": "d"}
    below_sample_table = RouteCalibrationTable.empty()
    for index in range(MIN_CALIBRATION_SAMPLE - 1):
        sample = RouteCalibrationSample(
            input_hash=f"hash-{index}",
            selected_route=ROUTE_QUICK,
            routing_regret=0.1,
            ready_without_rework=True,
            cost=1.0,
        )
        bucket = below_sample_table.bucket("quick-eligible").with_sample(sample)
        below_sample_table = below_sample_table.with_bucket(bucket)

    baseline = select_calibrated_route(
        input_hash=decision.input_hash,
        confidence=0.96,
        quick_eligible=True,
        table=below_sample_table,
        classifier_tier="cheap",
        allowed_tiers=allowed,
        tiers=tiers,
    )
    assert baseline.selected_route == ROUTE_DETERMINISTIC_TRIAGE
    assert baseline.response == "deterministic-triage-fallback"

    assert below_sample_table.bucket("quick-eligible").sample_count < MIN_CALIBRATION_SAMPLE

    after_extra = select_calibrated_route(
        input_hash=decision.input_hash,
        confidence=0.96,
        quick_eligible=True,
        table=below_sample_table,
        classifier_tier="cheap",
        allowed_tiers=allowed,
        tiers=tiers,
    )
    assert after_extra.selected_route == baseline.selected_route
    assert after_extra.response == baseline.response

    above_sample_table = RouteCalibrationTable.empty()
    bucket = RouteCalibrationTable.empty().bucket("quick-eligible")
    for index in range(MIN_CALIBRATION_SAMPLE):
        bucket = bucket.with_sample(
            RouteCalibrationSample(
                input_hash=f"stable-{index}",
                selected_route=ROUTE_QUICK,
                routing_regret=0.0,
                ready_without_rework=True,
                cost=1.0,
            )
        )
    above_sample_table = above_sample_table.with_bucket(bucket)
    calibrated = select_calibrated_route(
        input_hash=decision.input_hash,
        confidence=0.96,
        quick_eligible=True,
        table=above_sample_table,
        classifier_tier="cheap",
        allowed_tiers=allowed,
        tiers=tiers,
        candidate_costs={ROUTE_QUICK: 1.0, ROUTE_FULL_WORKFLOW: 5.0},
    )
    assert calibrated.selected_route == ROUTE_QUICK
    assert calibrated.mechanical_verification_required
    assert calibrated.routing_regret_tiebreak_cost == 1.0

    fixed = deterministic_route_for_class("empty-declared-scope")
    assert fixed["selectedRoute"] == ROUTE_QUICK
    assert fixed["readyWithoutRework"] is True


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
