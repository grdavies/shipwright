#!/usr/bin/env python3
"""Unit tests for workflow intelligence analysis CLI (PRD 280 phase 4)."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import workflow_intelligence as wi  # noqa: E402


def _seed_record(
    store: wi.WorkflowIntelligenceStore,
    *,
    graph_run_id: str,
    cohort_dimensions: dict[str, str],
    rework: float,
    updated_at: str,
    latency_p50: float,
) -> dict:
    metrics = wi.CohortMetrics(
        node_count=2,
        total_tokens=100,
        total_latency_ms=int(latency_p50 * 2),
        latency_p50_ms=latency_p50,
        latency_p95_ms=latency_p50 * 2,
        ready_without_rework=rework == 0.0,
        human_rework=rework > 0,
        rework_contribution=rework,
    )
    return store.upsert_record(
        graph_run_id=graph_run_id,
        deliver_run_id=f"deliver-{graph_run_id}",
        cohort_dimensions=cohort_dimensions,
        metrics=metrics,
        updated_at=updated_at,
    )


def test_compare_outputs_p50_p95(tmp_path: Path) -> None:
    store = wi.WorkflowIntelligenceStore(tmp_path)
    left_dims = {"workflowType": "ship", "riskClass": "standard"}
    right_dims = {"workflowType": "deliver", "riskClass": "standard"}
    left_key = wi.cohort_key(left_dims)
    right_key = wi.cohort_key(right_dims)
    _seed_record(
        store,
        graph_run_id="run-left",
        cohort_dimensions=left_dims,
        rework=0.1,
        updated_at="2026-08-19T10:00:00Z",
        latency_p50=100.0,
    )
    _seed_record(
        store,
        graph_run_id="run-right",
        cohort_dimensions=right_dims,
        rework=0.4,
        updated_at="2026-08-19T11:00:00Z",
        latency_p50=200.0,
    )

    compare_args = type(
        "CompareArgs",
        (),
        {
            "root": tmp_path,
            "left_key": left_key,
            "right_key": right_key,
            "left_dimensions": None,
            "right_dimensions": None,
        },
    )()

    result = wi.cmd_compare(compare_args)
    assert result["verdict"] == "pass"
    assert result["left"]["metrics"]["latencyP50Ms"] == 100.0
    assert result["right"]["metrics"]["latencyP50Ms"] == 200.0
    assert result["delta"]["latencyP50Ms"] == 100.0


def test_trend_and_top_rework(tmp_path: Path) -> None:
    store = wi.WorkflowIntelligenceStore(tmp_path)
    dims = {"workflowType": "ship", "riskClass": "low"}
    key = wi.cohort_key(dims)
    _seed_record(
        store,
        graph_run_id="run-a",
        cohort_dimensions=dims,
        rework=0.2,
        updated_at="2026-08-19T10:00:00Z",
        latency_p50=50.0,
    )
    _seed_record(
        store,
        graph_run_id="run-b",
        cohort_dimensions=dims,
        rework=0.8,
        updated_at="2026-08-19T12:00:00Z",
        latency_p50=150.0,
    )

    trend_args = type(
        "TrendArgs",
        (),
        {
            "root": tmp_path,
            "cohort_key": key,
            "dimensions": None,
            "since": "2026-08-19T11:00:00Z",
        },
    )()

    trend = wi.cmd_trend(trend_args)
    assert trend["pointCount"] == 1
    assert trend["points"][0]["graphRunId"] == "run-b"

    top_args = type(
        "TopArgs",
        (),
        {"root": tmp_path, "cohort_key": "", "limit": 2},
    )()

    top = wi.cmd_top_rework(top_args)
    assert top["contributors"][0]["graphRunId"] == "run-b"
    assert top["contributors"][0]["reworkContribution"] == 0.8
