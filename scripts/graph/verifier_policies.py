#!/usr/bin/env python3
"""Fail-closed verifier-edge policy evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class VerifierKind(str, Enum):
    MECHANICAL = "mechanical"
    EVIDENCE = "evidence"
    JUDGMENT = "judgment"
    SYNTHESIS = "synthesis"


PRIORITY = (
    VerifierKind.MECHANICAL,
    VerifierKind.EVIDENCE,
    VerifierKind.JUDGMENT,
    VerifierKind.SYNTHESIS,
)


@dataclass(frozen=True)
class VerifierResult:
    verifier_id: str
    kind: VerifierKind
    passed: bool
    evidence_ref: str = ""


@dataclass(frozen=True)
class VerificationVerdict:
    passed: bool
    decisive_kind: VerifierKind | None
    ordered_results: tuple[VerifierResult, ...]
    reason: str


def evaluate_verifiers(
    results: Iterable[VerifierResult],
    *,
    judgment_quorum: int = 1,
) -> VerificationVerdict:
    """Apply fixed verifier priority; mechanical failure is always terminal."""
    if judgment_quorum < 1:
        raise ValueError("judgment_quorum must be positive")
    grouped = {kind: [] for kind in PRIORITY}
    for result in results:
        grouped[result.kind].append(result)
    ordered = tuple(result for kind in PRIORITY for result in grouped[kind])

    mechanical = grouped[VerifierKind.MECHANICAL]
    if any(not result.passed for result in mechanical):
        return VerificationVerdict(
            False,
            VerifierKind.MECHANICAL,
            ordered,
            "failing mechanical verification cannot be overridden",
        )
    evidence = grouped[VerifierKind.EVIDENCE]
    if any(not result.passed for result in evidence):
        return VerificationVerdict(False, VerifierKind.EVIDENCE, ordered, "evidence failed")
    judgments = grouped[VerifierKind.JUDGMENT]
    if judgments and sum(result.passed for result in judgments) < judgment_quorum:
        return VerificationVerdict(
            False, VerifierKind.JUDGMENT, ordered, "judgment quorum not reached"
        )
    synthesis = grouped[VerifierKind.SYNTHESIS]
    if any(not result.passed for result in synthesis):
        return VerificationVerdict(
            False, VerifierKind.SYNTHESIS, ordered, "synthesis failed"
        )
    return VerificationVerdict(True, None, ordered, "all applicable verifier tiers passed")
