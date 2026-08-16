#!/usr/bin/env python3
"""Detector orchestration over a realized diff (PRD 272 R1–R6)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from graph.detectors.builtin import DETECTOR_RUNNERS
from graph.detectors.coverage import CoverageReport, build_coverage_report
from graph.detectors.registry import DEFAULT_DETECTORS, detector_by_id, load_registry
from graph.detectors.result import DetectorResult, union_required_capability_ids
from graph.detectors.unclassified import detect_unclassified


def run_detectors(
    changed_paths: tuple[str, ...],
    *,
    repo_root: Path | None = None,
) -> tuple[tuple[DetectorResult, ...], CoverageReport]:
    """Run all registered detectors plus unclassified escalation."""
    registry_payload = None
    if repo_root is not None:
        try:
            registry_payload = load_registry(repo_root)
        except (OSError, ValueError):
            registry_payload = None
    by_id = detector_by_id(registry_payload)
    specs = tuple(
        by_id[spec.id] for spec in DEFAULT_DETECTORS if spec.id in by_id
    )
    results: list[DetectorResult] = []
    for spec in specs:
        runner = DETECTOR_RUNNERS.get(spec.id)
        if runner is None:
            continue
        results.append(runner(spec, changed_paths))
    unclassified_result, _blind = detect_unclassified(changed_paths, specs)
    results.append(unclassified_result)
    coverage = build_coverage_report(changed_paths, specs)
    return tuple(results), coverage


def summarize_detection(
    results: tuple[DetectorResult, ...],
    coverage: CoverageReport,
) -> dict[str, Any]:
    return {
        "requiredCapabilityIds": list(union_required_capability_ids(results)),
        "resultCount": len(results),
        "coverage": coverage.to_dict(),
    }
