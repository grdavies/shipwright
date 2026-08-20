#!/usr/bin/env python3
"""Unit tests for measurement-learning status surfaces (PRD 280 phase 4)."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import workflow_intelligence as wi  # noqa: E402
from wave_status import (  # noqa: E402
    collect_cohort_drill_down,
    collect_measurement_learning_status,
    collect_rule_effectiveness_summary,
)


def test_rule_effectiveness_summary_missing(tmp_path: Path) -> None:
    result = collect_rule_effectiveness_summary(tmp_path)
    assert result["verdict"] == "pass"
    assert result["readOnly"] is True
    assert result["recommendationCount"] >= 0


def test_cohort_drill_down_empty(tmp_path: Path) -> None:
    result = collect_cohort_drill_down(tmp_path)
    assert result["verdict"] == "pass"
    assert result["present"] is False
    assert result["cohortCount"] == 0


def test_cohort_drill_down_with_records(tmp_path: Path) -> None:
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
    summary = collect_cohort_drill_down(tmp_path)
    assert summary["present"] is True
    assert summary["cohortCount"] == 1

    drill = collect_cohort_drill_down(tmp_path, cohort_key=str(record["cohortKey"]))
    assert drill["present"] is True
    assert drill["recordCount"] == 1
    assert drill["recentRuns"][0]["graphRunId"] == "graph-run-1"


def test_measurement_learning_status_read_only(tmp_path: Path) -> None:
    result = collect_measurement_learning_status(tmp_path)
    assert result["verdict"] == "pass"
    assert result["readOnly"] is True
    assert result["ruleEffectiveness"]["readOnly"] is True
    assert result["workflowIntelligence"]["readOnly"] is True
