#!/usr/bin/env python3
"""Evidence display and false-positive correction (PRD 272 R8)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from graph.detectors.result import DetectorResult


@dataclass(frozen=True)
class InjectionEvidence:
    """Operator-visible evidence for a single injected capability."""

    capability_id: str
    detector_id: str
    detector_version: str
    rule_id: str
    evidence_paths: tuple[str, ...]
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilityId": self.capability_id,
            "detectorId": self.detector_id,
            "detectorVersion": self.detector_version,
            "ruleId": self.rule_id,
            "evidencePaths": list(self.evidence_paths),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class FalsePositiveOverride:
    """Auditable false-positive correction labeled for learning (R8)."""

    capability_id: str
    detector_id: str
    actor: str
    reason: str
    diff_digest: str
    recorded_at: str
    label: str = "learning:false-positive-override"

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilityId": self.capability_id,
            "detectorId": self.detector_id,
            "actor": self.actor,
            "reason": self.reason,
            "diffDigest": self.diff_digest,
            "recordedAt": self.recorded_at,
            "label": self.label,
        }


def collect_injection_evidence(
    results: tuple[DetectorResult, ...],
) -> tuple[InjectionEvidence, ...]:
    """Every injected capability shows the evidence and rule that produced it."""
    items: list[InjectionEvidence] = []
    for result in results:
        if not result.required_capability_ids:
            continue
        paths = tuple(ref.path for ref in result.evidence)
        for capability_id in result.required_capability_ids:
            items.append(
                InjectionEvidence(
                    capability_id=capability_id,
                    detector_id=result.detector_id,
                    detector_version=result.detector_version,
                    rule_id=result.rule_id,
                    evidence_paths=paths,
                    detail=result.detail,
                )
            )
    return tuple(items)


def record_false_positive_override(
    *,
    capability_id: str,
    detector_id: str,
    actor: str,
    reason: str,
    diff_digest: str,
) -> FalsePositiveOverride:
    return FalsePositiveOverride(
        capability_id=capability_id,
        detector_id=detector_id,
        actor=actor,
        reason=reason,
        diff_digest=diff_digest,
        recorded_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def apply_overrides(
    results: tuple[DetectorResult, ...],
    overrides: tuple[FalsePositiveOverride, ...],
) -> tuple[DetectorResult, ...]:
    """Remove overridden capabilities while preserving audit trail on metadata."""
    if not overrides:
        return results
    waived = {item.capability_id for item in overrides}
    adjusted: list[DetectorResult] = []
    for result in results:
        filtered = tuple(
            cap for cap in result.required_capability_ids if cap not in waived
        )
        adjusted.append(
            DetectorResult(
                detector_id=result.detector_id,
                detector_version=result.detector_version,
                evidence=result.evidence,
                confidence=result.confidence,
                required_capability_ids=filtered,
                disposition=result.disposition,
                rule_id=result.rule_id,
                detail=result.detail,
            )
        )
    return tuple(adjusted)


def explain_payload(
    results: tuple[DetectorResult, ...],
    overrides: tuple[FalsePositiveOverride, ...] | None = None,
) -> dict[str, Any]:
    """Status/explain payload for detector injections."""
    evidence = collect_injection_evidence(results)
    payload: dict[str, Any] = {
        "injections": [item.to_dict() for item in evidence],
        "overrideLabels": [item.label for item in (overrides or ())],
    }
    if overrides:
        payload["overrides"] = [item.to_dict() for item in overrides]
    return payload
