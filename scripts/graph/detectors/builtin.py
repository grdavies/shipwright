#!/usr/bin/env python3
"""Individual mechanical risk detectors (PRD 272 R1/R2)."""
from __future__ import annotations

from graph.detectors.patterns import classify_path
from graph.detectors.registry import (
    CAPABILITY_API,
    CAPABILITY_AUTH,
    CAPABILITY_MIGRATION,
    CAPABILITY_SUPPLY_CHAIN,
    DETECTOR_API,
    DETECTOR_AUTH,
    DETECTOR_MIGRATION,
    DETECTOR_SUPPLY_CHAIN,
    DetectorSpec,
)
from graph.detectors.result import DetectorResult, EvidenceRef, hash_path_content


def _fire(
    spec: DetectorSpec,
    *,
    paths: tuple[str, ...],
    rule_id: str,
    detail: str,
    confidence: str = "high",
) -> DetectorResult:
    evidence = tuple(
        EvidenceRef(path=path, sha256=hash_path_content(path)) for path in paths
    )
    return DetectorResult(
        detector_id=spec.id,
        detector_version=spec.version,
        evidence=evidence,
        confidence=confidence,
        required_capability_ids=(spec.capability_id,),
        disposition="fire",
        rule_id=rule_id,
        detail=detail,
    )


def _no_fire(spec: DetectorSpec) -> DetectorResult:
    return DetectorResult(
        detector_id=spec.id,
        detector_version=spec.version,
        evidence=(),
        confidence="high",
        required_capability_ids=(),
        disposition="no-fire",
        rule_id="none",
        detail="no matching paths",
    )


def detect_migration(spec: DetectorSpec, changed_paths: tuple[str, ...]) -> DetectorResult:
    matched = tuple(
        path for path in changed_paths if classify_path(path, spec.intake_surfaces)
    )
    if not matched:
        return _no_fire(spec)
    return _fire(
        spec,
        paths=matched,
        rule_id="migration.path",
        detail="database or schema migration surface changed",
    )


def detect_auth(spec: DetectorSpec, changed_paths: tuple[str, ...]) -> DetectorResult:
    matched = tuple(
        path for path in changed_paths if classify_path(path, spec.intake_surfaces)
    )
    if not matched:
        return _no_fire(spec)
    return _fire(
        spec,
        paths=matched,
        rule_id="auth.surface",
        detail="authentication or authorization surface changed",
    )


def detect_api(spec: DetectorSpec, changed_paths: tuple[str, ...]) -> DetectorResult:
    matched = tuple(
        path for path in changed_paths if classify_path(path, spec.intake_surfaces)
    )
    if not matched:
        return _no_fire(spec)
    return _fire(
        spec,
        paths=matched,
        rule_id="api.surface",
        detail="public API or schema surface changed",
    )


def detect_supply_chain(
    spec: DetectorSpec, changed_paths: tuple[str, ...]
) -> DetectorResult:
    matched = tuple(
        path for path in changed_paths if classify_path(path, spec.intake_surfaces)
    )
    if not matched:
        return _no_fire(spec)
    return _fire(
        spec,
        paths=matched,
        rule_id="supply-chain.intake",
        detail="dependency or supply-chain intake surface changed",
    )


DETECTOR_RUNNERS = {
    DETECTOR_MIGRATION: detect_migration,
    DETECTOR_AUTH: detect_auth,
    DETECTOR_API: detect_api,
    DETECTOR_SUPPLY_CHAIN: detect_supply_chain,
}

CAPABILITY_BY_DETECTOR = {
    DETECTOR_MIGRATION: CAPABILITY_MIGRATION,
    DETECTOR_AUTH: CAPABILITY_AUTH,
    DETECTOR_API: CAPABILITY_API,
    DETECTOR_SUPPLY_CHAIN: CAPABILITY_SUPPLY_CHAIN,
}
