#!/usr/bin/env python3
"""Unit tests for workflow intelligence cohort store (PRD 280 phase 3)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import workflow_intelligence as wi  # noqa: E402


def test_cohort_key_is_content_addressed() -> None:
    dims_a = {
        "workflowType": "Deliver",
        "riskClass": "Standard",
        "modelTier": "build",
    }
    dims_b = {
        "modelTier": "build",
        "riskClass": "standard",
        "workflowType": "deliver",
    }
    assert wi.cohort_key(dims_a) == wi.cohort_key(dims_b)


def test_metrics_from_graph_snapshot() -> None:
    receipts = [
        {"durationMs": 100, "tokens": 10, "verdict": "pass"},
        {"durationMs": 300, "tokens": 20, "verdict": "fail"},
    ]
    telemetry = {"terminalVerdict": "ready", "humanRework": False}
    metrics = wi.metrics_from_graph_snapshot(receipts, telemetry)
    assert metrics.node_count == 2
    assert metrics.total_tokens == 30
    assert metrics.ready_without_rework is True
    assert metrics.rework_contribution == 0.5


def test_store_upsert_and_aggregate_dry_run(tmp_path: Path) -> None:
    store = wi.WorkflowIntelligenceStore(tmp_path)
    metrics = wi.CohortMetrics(
        node_count=1,
        total_tokens=5,
        total_latency_ms=50,
        latency_p50_ms=50.0,
        latency_p95_ms=50.0,
        ready_without_rework=True,
        human_rework=False,
        rework_contribution=0.0,
    )
    record = store.upsert_record(
        graph_run_id="graph-run-1",
        deliver_run_id="deliver-1",
        cohort_dimensions={"workflowType": "ship", "riskClass": "standard"},
        metrics=metrics,
        updated_at="2026-08-19T12:00:00Z",
    )
    assert record["graphRunId"] == "graph-run-1"
    assert len(record["cohortKey"]) == 64

    dry = store.aggregate_incremental(dry_run=True)
    assert dry["dryRun"] is True
    assert dry["pendingRecordCount"] == 1
    assert dry["cohortCount"] == 1
    assert dry["cursorAfter"] == ""

    written = store.aggregate_incremental(dry_run=False)
    assert written["dryRun"] is False
    assert written["cursorAfter"] == "2026-08-19T12:00:00Z"
    aggregate_path = store.aggregate_path(str(record["cohortKey"]))
    assert aggregate_path.is_file()
    payload = json.loads(aggregate_path.read_text(encoding="utf-8"))
    assert payload["sampleSize"] == 1
