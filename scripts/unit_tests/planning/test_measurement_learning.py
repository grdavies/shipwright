"""Hermetic fixtures for PRD 280 measurement + learning phase 5 (R3, R4, R7, R9, R11)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import planning_store_facade as ps_facade
import rule_effectiveness as reff
import workflow_intelligence as wi
from graph.dynamic_proposal import export_shadow_evaluation_inputs


def _canonical_graph() -> dict[str, object]:
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "measurement-learning-fixture"},
        "spec": {
            "nodes": [
                {
                    "id": "execute",
                    "kind": "command",
                    "target": {"step": "sw-execute"},
                    "resources": {"pool": "code-writers", "slots": 1, "timeoutSeconds": 300},
                    "isolation": {"mode": "worktree", "writeScope": "worktree"},
                    "verification": {"required": True, "strategy": "mechanical"},
                },
                {
                    "id": "verify",
                    "kind": "verifier",
                    "target": {"step": "sw-verify"},
                    "resources": {"pool": "code-writers", "slots": 1, "timeoutSeconds": 300},
                    "isolation": {"mode": "process", "writeScope": "read-only"},
                    "verification": {"required": True, "strategy": "evidence"},
                },
            ],
            "edges": [{"from": "execute", "to": "verify", "required": True}],
            "resourceLimits": {"maxConcurrency": 2, "maxDurationSeconds": 600},
            "verification": {"required": True, "failClosed": True},
        },
    }


def _seed_intelligence_store(root: Path) -> str:
    store = wi.WorkflowIntelligenceStore(root)
    dimensions = {
        "workflowType": "deliver",
        "riskClass": "standard",
        "modelTier": "build",
        "language": "python",
        "repoSize": "medium",
        "planPolicy": "canonical",
    }
    key = ""
    for idx, (p50, p95) in enumerate(((100.0, 200.0), (300.0, 500.0)), start=1):
        metrics = wi.CohortMetrics(
            node_count=4,
            total_tokens=120,
            total_latency_ms=900,
            latency_p50_ms=p50,
            latency_p95_ms=p95,
            ready_without_rework=False,
            human_rework=True,
            rework_contribution=0.25,
        )
        record = store.upsert_record(
            graph_run_id=f"fixture-run-{idx}",
            deliver_run_id="deliver-fixture",
            cohort_dimensions=dimensions,
            metrics=metrics,
        )
        key = str(record["cohortKey"])
    return key


def test_recommendations_report_emits_advisory_classes(tmp_path: Path) -> None:
    rule_id = "fixture-rule-alpha"
    for outcome in ("loaded", "loaded", "error"):
        reff.put_event(
            tmp_path,
            reff.build_record(
                rule_id=rule_id,
                surface="rules-load",
                provider="in-repo",
                outcome=outcome,
            ),
        )
    report = reff.recommendations_report(tmp_path)
    assert report["verdict"] == "pass"
    assert report["recommendationCount"] >= 1
    rec = next(item for item in report["recommendations"] if item["ruleId"] == rule_id)
    assert rec["recommendation"] in reff.RECOMMENDATION_CLASSES


def test_safety_retire_refused_without_waiver(tmp_path: Path) -> None:
    safety_id = "sw-guardrails"
    store_root = reff.resolve_store_root(tmp_path, provider="in-repo")
    for _ in range(3):
        reff.put_event(
            tmp_path,
            reff.build_record(
                rule_id=safety_id,
                surface="rules-load",
                provider="in-repo",
                outcome="error",
            ),
        )
    recommendation = reff.build_recommendation(
        safety_id,
        {
            "eventCount": 3,
            "errorCount": 3,
            "loadedCount": 0,
            "errorRate": 1.0,
            "loadSuccessRate": 0.0,
        },
        store_root=store_root,
    )
    assert recommendation["safetyBlocked"] is True
    assert recommendation["recommendation"] != "retire"


def test_cohort_aggregate_p50_p95_golden(tmp_path: Path) -> None:
    key = _seed_intelligence_store(tmp_path)
    store = wi.WorkflowIntelligenceStore(tmp_path)
    aggregate = store.aggregate_cohort(list(store.records_for_cohort(key)))
    assert aggregate["latencyP50Ms"] == pytest.approx(200.0)
    assert aggregate["latencyP95Ms"] == pytest.approx(290.0)
    assert aggregate["sampleSize"] == 2


def test_shadow_export_is_read_only_and_strips_metrics() -> None:
    canonical = _canonical_graph()
    candidate = json.loads(json.dumps(canonical))
    candidate["shadowScore"] = {"predictedLatencyMs": 1}
    exported = export_shadow_evaluation_inputs([candidate], canonical_graph=canonical)
    assert exported["verdict"] == "pass"
    assert exported["readOnlyAssert"] is True
    assert exported["mutatingBackendCalls"] == 0
    assert exported["inputs"]
    assert "shadowScore" not in exported["inputs"][0]["proposal"]


def test_shadow_export_disabled_is_skipped() -> None:
    exported = export_shadow_evaluation_inputs(
        [],
        canonical_graph=_canonical_graph(),
        shadow_enabled=False,
    )
    assert exported["verdict"] == "skipped"
    assert exported["mutatingBackendCalls"] == 0


def test_intelligence_shadow_export_from_cohort(tmp_path: Path) -> None:
    _seed_intelligence_store(tmp_path)
    exported = wi.export_shadow_candidates(
        tmp_path,
        canonical_graph=_canonical_graph(),
        limit=1,
    )
    assert exported["verdict"] == "pass"
    assert exported["readOnlyAssert"] is True
    assert exported["mutatingBackendCalls"] == 0


def test_doctor_refuses_tracked_prd_bodies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": "planning",
            }
        }
    }
    prd_path = tmp_path / "docs" / "prds" / "280-fixture" / "280-prd-fixture.md"
    prd_path.parent.mkdir(parents=True)
    prd_path.write_text("# fixture\n", encoding="utf-8")

    monkeypatch.setattr(
        ps_facade,
        "tracked_planning_body_paths",
        lambda _root: ["docs/prds/280-fixture/280-prd-fixture.md"],
    )
    monkeypatch.setattr(
        "planning_artifact_handle.issue_store_separate_project_effective",
        lambda _root, _cfg: True,
    )

    result = ps_facade.doctor_tracked_prd_bodies(tmp_path, cfg)
    assert result["verdict"] == "fail"
    assert result["halt"] == "tracked-prd-bodies-in-code-repo"
