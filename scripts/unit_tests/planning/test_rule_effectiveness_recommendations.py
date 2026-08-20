"""PRD 280 phase 2 — rule recommendation classifier and safety retire refusal (R3, R4, R5)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from rule_effectiveness import (
    aggregate_rule_metrics,
    build_record,
    build_recommendation,
    enforce_safety_exception,
    is_safety_tagged,
    put_event,
    recommendations_report,
    record_waiver,
    resolve_store_root,
)


def test_each_recommendation_class_emitted() -> None:
    metrics_cases = [
        ({"eventCount": 0}, "re-evaluate"),
        (
            {
                "eventCount": 5,
                "loadedCount": 5,
                "errorCount": 0,
                "loadSuccessRate": 1.0,
                "errorRate": 0.0,
            },
            "retain",
        ),
        (
            {
                "eventCount": 4,
                "loadedCount": 1,
                "filteredCount": 3,
                "errorCount": 1,
                "loadSuccessRate": 0.25,
                "errorRate": 0.25,
            },
            "narrow",
        ),
        (
            {
                "eventCount": 2,
                "errorCount": 2,
                "errorRate": 1.0,
                "loadSuccessRate": 0.0,
            },
            "retire",
        ),
    ]
    store = Path("/tmp/rule-eff-test-store")
    for metrics, expected in metrics_cases:
        rec = build_recommendation("custom-rule", metrics, store_root=store)
        assert rec["recommendation"] == expected
        assert rec["reason"]
        assert 0 <= rec["confidence"] <= 1
        assert "eventCount" in rec["supportingMetrics"]


def test_safety_rule_retire_refused_without_waiver(tmp_path: Path) -> None:
    store_root = resolve_store_root(tmp_path, provider="in-repo")
    rule_id = "sw-guardrails"
    assert is_safety_tagged(rule_id)
    metrics = {
        "eventCount": 3,
        "errorCount": 3,
        "errorRate": 1.0,
        "loadSuccessRate": 0.0,
    }
    rec = build_recommendation(rule_id, metrics, store_root=store_root)
    assert rec["safetyBlocked"] is True
    assert rec["recommendation"] != "retire"
    assert rec["recommendation"] == "re-evaluate"

    final, blocked, _ = enforce_safety_exception(rule_id, "retire", store_root)
    assert blocked is True
    assert final == "re-evaluate"

    record_waiver(
        store_root,
        rule_id=rule_id,
        recommendation="retire",
        approved_by="operator",
        reason="fixture waiver",
    )
    final, blocked, _ = enforce_safety_exception(rule_id, "retire", store_root)
    assert blocked is False
    assert final == "retire"


def test_recommendations_report_includes_audit_handoff(tmp_path: Path) -> None:
    record = build_record(
        rule_id="custom-telemetry-rule",
        surface="rules-load",
        provider="in-repo",
        outcome="loaded",
    )
    put_event(tmp_path, record, provider="in-repo")
    report = recommendations_report(tmp_path, provider="in-repo")
    assert report["verdict"] == "pass"
    assert report["auditHandoff"] == "/sw-memory-audit"
    assert report["reportCommand"].endswith("recommendations report")
    assert report["recommendationCount"] >= 1
    sample = report["recommendations"][0]
    assert "supportingMetrics" in sample
    assert "confidence" in sample


def test_aggregate_rule_metrics_from_events() -> None:
    events = [
        {"ruleId": "a", "outcome": "loaded"},
        {"ruleId": "a", "outcome": "error"},
        {"ruleId": "b", "outcome": "unreachable"},
    ]
    metrics = aggregate_rule_metrics(events, "a")
    assert metrics["eventCount"] == 2
    assert metrics["loadedCount"] == 1
    assert metrics["errorCount"] == 1
    assert metrics["errorRate"] == 0.5


def test_merge_recommendation_class_emitted() -> None:
    metrics = {
        "eventCount": 4,
        "loadedCount": 2,
        "errorCount": 0,
        "filteredCount": 0,
        "loadSuccessRate": 0.5,
        "errorRate": 0.0,
    }
    rec = build_recommendation("low-signal-rule", metrics, store_root=Path("/tmp/rule-eff-merge"))
    assert rec["recommendation"] == "merge"
