#!/usr/bin/env python3
"""Cutover evidence + per-gap closeout fixtures (PRD 271 R16, D1–D5)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.cutover import (  # noqa: E402
    GAP_CLOSEOUT_ORDER,
    RUNTIME_V2_STAGE_ORDER,
    CutoverDriver,
    CutoverError,
    RuntimeV2Closeout,
    RuntimeV2CutoverStage,
    assert_decision_log_binding,
    decision_log_checklists,
    extend_cutover_driver_kill_switch_serial,
)
from graph.execution_receipts import ExecutionReceiptJournal  # noqa: E402
from graph.observability import GraphObservability  # noqa: E402
from graph.resource_pools import ResourcePoolRegistry  # noqa: E402
from graph.scheduler import GraphScheduler, NodeExecutionResult  # noqa: E402
from graph.scheduling_modes import SERIAL_EQUIVALENT_MAX_CONCURRENCY  # noqa: E402
from graph.timing_events import TimingCategory, observed_execution_overlap  # noqa: E402


def _node(node_id: str) -> dict[str, object]:
    return {
        "id": node_id,
        "kind": "command",
        "target": {"step": f"sw-{node_id}"},
        "resources": {"pool": "code-writers", "slots": 1, "timeoutSeconds": 30},
        "isolation": {"mode": "process", "writeScope": "read-only"},
        "verification": {"required": True, "strategy": "mechanical"},
    }


def _parallel_graph(*, max_concurrency: int = 2) -> dict[str, object]:
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "cutover-overlap"},
        "spec": {
            "nodes": [_node("a"), _node("b"), _node("join")],
            "edges": [
                {"from": "a", "to": "join", "required": True},
                {"from": "b", "to": "join", "required": True},
            ],
            "resourceLimits": {
                "maxConcurrency": max_concurrency,
                "maxDurationSeconds": 600,
            },
            "verification": {"required": True, "failClosed": True},
        },
    }


def _overlapping_timing_events() -> list[dict[str, object]]:
    return [
        {
            "seq": 1,
            "nodeId": "a",
            "category": TimingCategory.EXECUTION.value,
            "durationMs": 50,
            "monotonicStartMs": 0,
            "wallClockStartMs": 1,
            "schedulerEpoch": 0,
        },
        {
            "seq": 2,
            "nodeId": "b",
            "category": TimingCategory.EXECUTION.value,
            "durationMs": 40,
            "monotonicStartMs": 10,
            "wallClockStartMs": 2,
            "schedulerEpoch": 0,
        },
    ]


def test_per_gap_closeout_and_overlap_evidence(tmp_path: Path) -> None:
    closeout = RuntimeV2Closeout()
    events = _overlapping_timing_events()
    overlap = closeout.collect_overlap_evidence(
        timing_events=events,
        configured_max_concurrency=2,
    )
    closeout.overlap_evidence = overlap
    assert overlap.observed_overlap_ge_2 is True
    assert overlap.sufficient_for_cutover is True
    assert observed_execution_overlap(events) is True

    serial_only = closeout.collect_overlap_evidence(
        timing_events=events,
        configured_max_concurrency=SERIAL_EQUIVALENT_MAX_CONCURRENCY,
    )
    assert serial_only.sufficient_for_cutover is False
    assert "kill-switch" in serial_only.reason

    config_only = closeout.collect_overlap_evidence(
        timing_events=[],
        configured_max_concurrency=4,
    )
    assert config_only.sufficient_for_cutover is False

    assert [entry.issue for entry in GAP_CLOSEOUT_ORDER] == [674, 675, 681, 676, 682]

    closeout.close_gap(
        674,
        requirement_ids_green=("R1", "R1a", "R1b", "R2a", "R3"),
        overlap_in_receipts=True,
    )
    closeout.close_gap(675, requirement_ids_green=("R4", "R5", "R6"))
    closeout.close_gap(681, requirement_ids_green=("R9", "R10", "R14"))
    closeout.close_gap(676, requirement_ids_green=("R7", "R7a", "R8"))
    closeout.close_gap(
        682,
        requirement_ids_green=("R11", "R11a", "R11b"),
        overlap_in_receipts=True,
    )

    checklist = closeout.r16_closeout_checklist(
        gap_results={
            issue: {"passed": True, "overlapInReceipts": issue in {674, 682}}
            for issue in (674, 675, 681, 676, 682)
        }
    )
    assert len(checklist) == 5
    assert all(item.runnable for item in checklist)
    assert all(item.passed for item in checklist)

    closeout.promote_runtime_v2_stage(
        RuntimeV2CutoverStage.CUTOVER_EVIDENCE,
        overlap=overlap,
    )
    assert closeout.stage is RuntimeV2CutoverStage.CUTOVER_EVIDENCE

    driver = CutoverDriver()
    driver.activate_kill_switch(actor="operator", activated_at="2026-08-15T00:00:00Z")
    lane = extend_cutover_driver_kill_switch_serial(driver)
    assert lane.max_concurrency == SERIAL_EQUIVALENT_MAX_CONCURRENCY
    assert driver.effective_plan_policy() == "canonical"

    contract = closeout.rollback_resume_contract()
    assert contract.serial_lane.max_concurrency == SERIAL_EQUIVALENT_MAX_CONCURRENCY
    assert contract.reentry_command == "/sw-status"
    assert contract.session_detach_safe is True
    assert contract.rollback_mapping["graphNodeStep"] == "ship-steps.currentStep"

    clock_value = 1000.0

    def monotonic() -> float:
        nonlocal clock_value
        clock_value += 0.02
        return clock_value

    journal = ExecutionReceiptJournal(tmp_path / "receipts")
    scheduler = GraphScheduler(
        lambda node: NodeExecutionResult(
            verdict="pass",
            output={"node": node["id"]},
            model="fixture",
            duration_ms=20,
        ),
        receipts=journal,
        pools=ResourcePoolRegistry.from_config(limits={"code-writers": 2}),
        clock=monotonic,
    )
    result = scheduler.run(
        _parallel_graph(),
        run_id="cutover-overlap-run",
        internal_only=True,
    )
    assert result.verdict == "pass"
    timing_events = journal.list_timing_events()
    receipt_overlap = closeout.collect_overlap_evidence(
        timing_events=timing_events,
        configured_max_concurrency=2,
    )
    assert receipt_overlap.observed_overlap_ge_2 is True

    obs = result.observability(_parallel_graph())
    assert obs.execution_mode() == "concurrent"

    with pytest.raises(CutoverError, match="requires observed in-flight overlap"):
        RuntimeV2Closeout().close_gap(
            674,
            requirement_ids_green=("R1",),
            overlap_in_receipts=False,
        )


def test_decision_log_two_prd_packaging() -> None:
    items = decision_log_checklists()["D1"]
    assert all(item.passed for item in items)
    assert any("two PRDs" in item.assertion for item in items)
    assert any("mega-PRD" in item.assertion for item in items)
    assert_decision_log_binding()


def test_decision_log_sw_ship_ux() -> None:
    items = decision_log_checklists()["D2"]
    assert all(item.passed for item in items)
    assert any("/sw-ship" in item.assertion for item in items)


def test_decision_log_no_sw_graph_commands() -> None:
    items = decision_log_checklists()["D3"]
    assert all(item.passed for item in items)
    assert any("sw-graph" in item.assertion for item in items)


def test_decision_log_p0_dispositions_binding() -> None:
    items = decision_log_checklists()["D4"]
    assert len(items) == 6
    assert all(item.passed for item in items)
    assertions = " ".join(item.assertion for item in items)
    assert "cancel fencing" in assertions
    assert "R14" in assertions
    assert "R5a" in assertions
    assert "owning loop" in assertions
    assert "in-flight" in assertions


def test_decision_log_remaining_dispositions_binding() -> None:
    items = decision_log_checklists()["D5"]
    assert all(item.passed for item in items)
    ids = {item.decision_id for item in items}
    assert "D5-A" in ids
    assert "D5-G" in ids
    assert "D5-G4" in ids
    assert len(RUNTIME_V2_STAGE_ORDER) == 6
