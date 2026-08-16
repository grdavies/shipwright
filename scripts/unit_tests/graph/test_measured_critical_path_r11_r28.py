#!/usr/bin/env python3
"""Measured critical-path attribution from append-only timing events (PRD 271 R11/R28)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.execution_receipts import ExecutionReceiptJournal  # noqa: E402
from graph.observability import GraphObservability  # noqa: E402
from graph.scheduler import GraphScheduler, NodeExecutionResult  # noqa: E402
from graph.resource_pools import ResourcePoolRegistry  # noqa: E402
from graph.timing_events import (  # noqa: E402
    TimingCategory,
    aggregate_timing_events,
    causal_critical_path,
    observed_execution_overlap,
)


def _node(node_id: str, **extra: object) -> dict[str, object]:
    return {
        "id": node_id,
        "kind": "command",
        "resources": {
            "pool": "code-writers",
            "slots": 1,
            "timeoutSeconds": 30,
        },
        "isolation": {"mode": "process", "writeScope": "read-only"},
        "verification": {"required": True, "strategy": "mechanical"},
        **extra,
    }


def _parallel_graph() -> dict[str, object]:
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "timing-parallel"},
        "spec": {
            "nodes": [
                _node("a"),
                _node("b"),
                _node("join"),
            ],
            "edges": [
                {"from": "a", "to": "join", "required": True},
                {"from": "b", "to": "join", "required": True},
            ],
            "resourceLimits": {"maxConcurrency": 2, "maxDurationSeconds": 600},
            "verification": {"required": True, "failClosed": True},
        },
    }


def test_bookkeeping_excluded_from_attribution() -> None:
    events = [
        {
            "seq": 1,
            "nodeId": "a",
            "category": TimingCategory.EXECUTION.value,
            "durationMs": 40,
            "monotonicStartMs": 0,
            "wallClockStartMs": 1_700_000_000_000,
            "schedulerEpoch": 0,
        },
        {
            "seq": 2,
            "nodeId": "__bookkeeping__",
            "category": TimingCategory.BOOKKEEPING.value,
            "durationMs": 25,
            "monotonicStartMs": 10,
            "wallClockStartMs": 1_700_000_000_010,
            "schedulerEpoch": 0,
        },
    ]
    agg = aggregate_timing_events(events)
    assert agg["a"].attributed_ms == 40
    assert agg["a"].execution_ms == 40
    assert "__bookkeeping__" not in agg


def test_causal_critical_path_no_double_count_parallel_branches() -> None:
    events = [
        {
            "seq": 1,
            "nodeId": "a",
            "category": TimingCategory.EXECUTION.value,
            "durationMs": 10,
            "monotonicStartMs": 0,
            "wallClockStartMs": 1,
            "schedulerEpoch": 0,
        },
        {
            "seq": 2,
            "nodeId": "b",
            "category": TimingCategory.EXECUTION.value,
            "durationMs": 30,
            "monotonicStartMs": 0,
            "wallClockStartMs": 1,
            "schedulerEpoch": 0,
        },
        {
            "seq": 3,
            "nodeId": "join",
            "category": TimingCategory.EXECUTION.value,
            "durationMs": 5,
            "monotonicStartMs": 30,
            "wallClockStartMs": 1,
            "schedulerEpoch": 0,
        },
    ]
    agg = aggregate_timing_events(events)
    path = causal_critical_path(
        ("a", "b", "join"),
        {"a": (), "b": (), "join": ("a", "b")},
        agg,
    )
    assert path["omitted"] is False
    assert path["durationMs"] == 35  # 30 (b) + 5 (join), not 10+30+5
    assert [item["nodeId"] for item in path["nodes"]] == ["b", "join"]


def test_observed_execution_overlap_detects_concurrency() -> None:
    overlapping = [
        {
            "seq": 1,
            "nodeId": "a",
            "category": TimingCategory.EXECUTION.value,
            "durationMs": 20,
            "monotonicStartMs": 0,
            "wallClockStartMs": 1,
            "schedulerEpoch": 0,
        },
        {
            "seq": 2,
            "nodeId": "b",
            "category": TimingCategory.EXECUTION.value,
            "durationMs": 20,
            "monotonicStartMs": 5,
            "wallClockStartMs": 1,
            "schedulerEpoch": 0,
        },
    ]
    assert observed_execution_overlap(overlapping) is True
    serial = [
        {
            "seq": 1,
            "nodeId": "a",
            "category": TimingCategory.EXECUTION.value,
            "durationMs": 10,
            "monotonicStartMs": 0,
            "wallClockStartMs": 1,
            "schedulerEpoch": 0,
        },
        {
            "seq": 2,
            "nodeId": "b",
            "category": TimingCategory.EXECUTION.value,
            "durationMs": 10,
            "monotonicStartMs": 10,
            "wallClockStartMs": 1,
            "schedulerEpoch": 0,
        },
    ]
    assert observed_execution_overlap(serial) is False


def test_scheduler_records_timing_events(tmp_path: Path) -> None:
    clock_value = 1000.0
    step = 0.01

    def monotonic() -> float:
        nonlocal clock_value
        clock_value += step
        return clock_value

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        node_id = str(node["id"])
        duration = 15 if node_id == "b" else 5
        return NodeExecutionResult(
            verdict="pass",
            output={"node": node_id},
            model="fixture",
            duration_ms=duration,
        )

    journal = ExecutionReceiptJournal(tmp_path / "receipts")
    pools = ResourcePoolRegistry.from_config(limits={"code-writers": 2})
    scheduler = GraphScheduler(
        execute,
        receipts=journal,
        pools=pools,
        clock=monotonic,
    )
    result = scheduler.run(
        _parallel_graph(),
        run_id="timing-run",
        internal_only=True,
    )
    assert result.verdict == "pass"
    events = journal.list_timing_events()
    assert events
    categories = {event["category"] for event in events}
    assert TimingCategory.EXECUTION.value in categories
    assert TimingCategory.BOOKKEEPING.value in categories
    agg = aggregate_timing_events(events)
    assert "a" in agg and "b" in agg
    assert agg["a"].execution_ms > 0
    assert agg["b"].execution_ms > 0
    assert agg["a"].by_category.get("fan-in-wait", 0) >= 0
    bookkeeping = [e for e in events if e["category"] == TimingCategory.BOOKKEEPING.value]
    assert bookkeeping

    obs = result.observability(_parallel_graph())
    measured = obs.measured_critical_path()
    assert measured.get("measured") is True
    assert measured["durationMs"] >= 20


def test_explain_plan_stays_estimate_only_with_timing_events() -> None:
    graph = _parallel_graph()
    events = [
        {
            "seq": 1,
            "nodeId": "a",
            "category": TimingCategory.EXECUTION.value,
            "durationMs": 50,
            "monotonicStartMs": 0,
            "wallClockStartMs": 1,
            "schedulerEpoch": 0,
        },
    ]
    obs = GraphObservability(
        graph,
        receipts=[],
        estimated_durations={"a": 4, "b": 2, "join": 1},
        timing_events=events,
    )
    plan = obs.explain_plan()
    assert plan["criticalPathLabel"] == "estimated"
    assert plan["readOnly"] is True

    explain = obs.explain("a")
    assert explain.get("timingAttribution") is not None
    assert explain["timingAttribution"]["executionMs"] == 50
