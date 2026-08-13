#!/usr/bin/env python3
"""Cutover parity and fail-closed coverage regression fixtures."""
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
from graph.resource_pools import ResourcePoolRegistry  # noqa: E402
from graph.scheduler import GraphScheduler, NodeExecutionResult  # noqa: E402


def _deliver_plan() -> dict[str, object]:
    return {
        "version": 1,
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
            if edge["from"] != "verify" and edge["to"] != "verify"
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
