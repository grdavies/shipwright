#!/usr/bin/env python3
"""PRD 272 phase-1 detector contract tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.detectors import (  # noqa: E402
    CAPABILITY_AUTH,
    CAPABILITY_MIGRATION,
    CAPABILITY_STANDARD_REVIEW,
    CAPABILITY_SUPPLY_CHAIN,
    DetectorParseError,
    compile_verification_nodes,
    explain_payload,
    parse_detector_result,
    record_false_positive_override,
    run_detectors,
    union_required_capability_ids,
)
from graph.detectors.compiler import attach_injection_metadata  # noqa: E402
from graph.detectors.evidence import apply_overrides  # noqa: E402
from graph.detectors.registry import load_registry  # noqa: E402


def test_detector_result_schema_and_fail_closed_parse() -> None:
    payload = {
        "schemaVersion": 1,
        "detectorId": "workflow.detector.migration",
        "detectorVersion": "1.0.0",
        "evidence": [{"path": "db/migrations/001.sql", "sha256": "abc"}],
        "confidence": "high",
        "requiredCapabilityIds": ["workflow.capability.migration-validation"],
        "disposition": "fire",
        "ruleId": "migration.path",
    }
    result = parse_detector_result(payload)
    assert result.detector_id == "workflow.detector.migration"
    assert result.required_capability_ids == ("workflow.capability.migration-validation",)

    with pytest.raises(DetectorParseError):
        parse_detector_result({"schemaVersion": 1, "detectorId": "x"})

    registry = load_registry(_SCRIPTS.parent)
    families = registry["families"]
    assert "workflow.detectors" in families
    assert "workflow.requiredCapabilities" in families
    assert "workflow.detectorCoverage" in families


def test_detector_result_attaches_required_capability() -> None:
    results, _coverage = run_detectors(("src/auth/login.py",))
    caps = union_required_capability_ids(results)
    assert CAPABILITY_AUTH in caps
    nodes = compile_verification_nodes(results)
    node_caps = {
        node["metadata"]["requiredCapabilityId"] for node in nodes
    }
    assert CAPABILITY_AUTH in node_caps


def test_four_detectors_compile_to_verification_nodes() -> None:
    changed = (
        "db/migrations/001_init.sql",
        "src/auth/session.py",
        "openapi.yaml",
        "package-lock.json",
    )
    results, coverage = run_detectors(changed)
    caps = union_required_capability_ids(results)
    assert CAPABILITY_MIGRATION in caps
    assert CAPABILITY_AUTH in caps
    assert "workflow.capability.api-compatibility" in caps
    assert CAPABILITY_SUPPLY_CHAIN in caps
    nodes = compile_verification_nodes(results)
    assert len(nodes) == len(caps)
    for node in nodes:
        assert node["kind"] == "verifier"
        assert node["metadata"]["requiredCapabilityId"] in caps
    assert coverage.classified_paths == changed


def test_unclassified_path_escalates_standard_review() -> None:
    results, coverage = run_detectors(("docs/random/new-surface.md",))
    caps = union_required_capability_ids(results)
    assert CAPABILITY_STANDARD_REVIEW in caps
    assert coverage.blind_spot_paths == ("docs/random/new-surface.md",)
    report = coverage.to_dict()
    assert report["blindSpotCount"] == 1
    assert "docs/random/new-surface.md" in report["blindSpotPaths"]


def test_injection_shows_evidence_and_fp_correction() -> None:
    results, _ = run_detectors(("package.json",))
    explain = explain_payload(results)
    assert explain["injections"]
    injection = explain["injections"][0]
    assert injection["evidencePaths"]
    assert injection["ruleId"]
    override = record_false_positive_override(
        capability_id=CAPABILITY_SUPPLY_CHAIN,
        detector_id="workflow.detector.supply-chain",
        actor="operator@test",
        reason="fixture-only lockfile churn",
        diff_digest="deadbeef",
    )
    adjusted = apply_overrides(results, (override,))
    adjusted_caps = union_required_capability_ids(adjusted)
    assert CAPABILITY_SUPPLY_CHAIN not in adjusted_caps
    explain_with_override = explain_payload(results, overrides=(override,))
    assert "learning:false-positive-override" in explain_with_override["overrideLabels"]
    assert explain_with_override["overrides"][0]["actor"] == "operator@test"


def test_typed_capability_ids_through_compile_metadata() -> None:
    results, _ = run_detectors(("package.json",))
    graph = attach_injection_metadata(
        {"apiVersion": "shipwright.dev/v1alpha1", "kind": "WorkflowGraph", "metadata": {}},
        results,
    )
    metadata = graph["metadata"]
    assert all(
        cap.startswith("workflow.capability.")
        for cap in metadata["requiredCapabilityIds"]
    )
    roundtrip = json.loads(json.dumps(metadata["detectorResults"]))
    fired = next(item for item in roundtrip if item.get("requiredCapabilityIds"))
    parsed = parse_detector_result(fired)
    assert parsed.required_capability_ids
