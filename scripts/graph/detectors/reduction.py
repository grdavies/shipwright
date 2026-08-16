#!/usr/bin/env python3
"""Requirement reduction authorization (PRD 272 R7)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from graph.detectors.evidence import FalsePositiveOverride, apply_overrides
from graph.detectors.result import DetectorResult
from graph.detectors.runner import run_detectors


@dataclass(frozen=True)
class HumanWaiver:
    """Recorded human authorization to waive a specific capability."""

    capability_id: str
    actor: str
    reason: str
    recorded_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilityId": self.capability_id,
            "actor": self.actor,
            "reason": self.reason,
            "recordedAt": self.recorded_at,
            "kind": "human-waiver",
        }


@dataclass(frozen=True)
class MechanicalNoFire:
    """Detector no-fire path with version + diff digest audit trail."""

    capability_id: str
    detector_id: str
    detector_version: str
    diff_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "capabilityId": self.capability_id,
            "detectorId": self.detector_id,
            "detectorVersion": self.detector_version,
            "diffDigest": self.diff_digest,
            "kind": "mechanical-no-fire",
        }


@dataclass(frozen=True)
class ReductionAuthorization:
    """Whether a capability reduction is authorized."""

    authorized: bool
    capability_id: str
    path: str
    reason: str
    receipt: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "authorized": self.authorized,
            "capabilityId": self.capability_id,
            "path": self.path,
            "reason": self.reason,
        }
        if self.receipt is not None:
            payload["receipt"] = dict(self.receipt)
        return payload


def record_human_waiver(
    *,
    capability_id: str,
    actor: str,
    reason: str,
) -> HumanWaiver:
    return HumanWaiver(
        capability_id=capability_id,
        actor=actor,
        reason=reason,
        recorded_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def authorize_reduction(
    capability_id: str,
    *,
    waivers: tuple[HumanWaiver, ...] = (),
    no_fire: tuple[MechanicalNoFire, ...] = (),
    model_narrative: str | None = None,
) -> ReductionAuthorization:
    """Authorize reduction only via mechanical no-fire or recorded human waiver."""
    if model_narrative and not waivers and not no_fire:
        return ReductionAuthorization(
            authorized=False,
            capability_id=capability_id,
            path="model-narrative",
            reason="model-authored narrative is never sufficient to reduce requirements",
        )
    for waiver in waivers:
        if waiver.capability_id == capability_id:
            return ReductionAuthorization(
                authorized=True,
                capability_id=capability_id,
                path="human-waiver",
                reason="recorded human authorization",
                receipt=waiver.to_dict(),
            )
    for record in no_fire:
        if record.capability_id == capability_id:
            return ReductionAuthorization(
                authorized=True,
                capability_id=capability_id,
                path="mechanical-no-fire",
                reason="detector no-fire with version and diff digest",
                receipt=record.to_dict(),
            )
    return ReductionAuthorization(
        authorized=False,
        capability_id=capability_id,
        path="unreviewed",
        reason="unreviewed reductions fail closed",
    )


def mechanical_no_fire_for_paths(
    capability_id: str,
    detector_id: str,
    detector_version: str,
    changed_paths: tuple[str, ...],
    *,
    diff_digest: str,
) -> MechanicalNoFire | None:
    """Return a no-fire record when the detector does not fire on the realized diff."""
    results, _ = run_detectors(changed_paths)
    fired_caps = {
        cap
        for result in results
        if result.detector_id == detector_id
        for cap in result.required_capability_ids
    }
    if capability_id in fired_caps:
        return None
    return MechanicalNoFire(
        capability_id=capability_id,
        detector_id=detector_id,
        detector_version=detector_version,
        diff_digest=diff_digest,
    )


def apply_authorized_reductions(
    results: tuple[DetectorResult, ...],
    authorizations: tuple[ReductionAuthorization, ...],
) -> tuple[DetectorResult, ...]:
    """Apply only authorized reductions; refuse unreviewed capability drops."""
    overrides: list[FalsePositiveOverride] = []
    for auth in authorizations:
        if not auth.authorized:
            continue
        receipt = auth.receipt or {}
        overrides.append(
            FalsePositiveOverride(
                capability_id=auth.capability_id,
                detector_id=str(receipt.get("detectorId") or "human-waiver"),
                actor=str(receipt.get("actor") or "system"),
                reason=str(receipt.get("reason") or auth.reason),
                diff_digest=str(receipt.get("diffDigest") or ""),
                recorded_at=str(
                    receipt.get("recordedAt")
                    or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                ),
            )
        )
    return apply_overrides(results, tuple(overrides))
