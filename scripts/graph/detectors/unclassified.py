#!/usr/bin/env python3
"""Unclassified path escalation (PRD 272 R5)."""
from __future__ import annotations

from graph.detectors.patterns import classify_path
from graph.detectors.registry import CAPABILITY_STANDARD_REVIEW, DetectorSpec
from graph.detectors.result import DetectorResult, EvidenceRef, hash_path_content

UNCLASSIFIED_DETECTOR_ID = "workflow.detector.unclassified"
UNCLASSIFIED_VERSION = "1.0.0"


def covered_by_any_detector(
    path: str,
    detector_specs: tuple[DetectorSpec, ...],
) -> bool:
    for spec in detector_specs:
        if classify_path(path, spec.intake_surfaces):
            return True
    return False


def detect_unclassified(
    changed_paths: tuple[str, ...],
    detector_specs: tuple[DetectorSpec, ...],
) -> tuple[DetectorResult, tuple[str, ...]]:
    """Return escalation result and blind-spot paths outside every detector scope."""
    blind_spots = tuple(
        path
        for path in changed_paths
        if not covered_by_any_detector(path, detector_specs)
    )
    if not blind_spots:
        return (
            DetectorResult(
                detector_id=UNCLASSIFIED_DETECTOR_ID,
                detector_version=UNCLASSIFIED_VERSION,
                evidence=(),
                confidence="high",
                required_capability_ids=(),
                disposition="no-fire",
                rule_id="unclassified.none",
                detail="all changed paths classified",
            ),
            blind_spots,
        )
    evidence = tuple(
        EvidenceRef(path=path, sha256=hash_path_content(path)) for path in blind_spots
    )
    return (
        DetectorResult(
            detector_id=UNCLASSIFIED_DETECTOR_ID,
            detector_version=UNCLASSIFIED_VERSION,
            evidence=evidence,
            confidence="medium",
            required_capability_ids=(CAPABILITY_STANDARD_REVIEW,),
            disposition="escalate",
            rule_id="unclassified.path",
            detail="path outside detector classification matrix",
        ),
        blind_spots,
    )
