#!/usr/bin/env python3
"""Fail-closed verifier-edge policy evaluation."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

JUDGMENT_INDEPENDENCE_AXES = (
    "modelFamily",
    "persona",
    "promptTemplate",
    "contextSource",
    "evidenceSource",
)

# Self-declared payload keys are never used for independence counting.
_SELF_DECLARED_PAYLOAD_KEYS = frozenset(
    {
        "modelFamily",
        "model_family",
        "persona",
        "promptTemplate",
        "prompt_template",
        "contextSource",
        "context_source",
        "evidenceSource",
        "evidence_source",
        "payload",
        "selfDeclared",
        "declared",
    }
)

_CORRELATED_UNKNOWN = "__correlated_unknown__"


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
    dispatch_record: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class VerificationVerdict:
    passed: bool
    decisive_kind: VerifierKind | None
    ordered_results: tuple[VerifierResult, ...]
    reason: str


def _recorded_dispatch(dispatch_record: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return dispatcher-recorded fields; ignore self-declared payload bodies."""
    recorded = dispatch_record.get("dispatch")
    if isinstance(recorded, Mapping):
        return recorded
    return {
        key: value
        for key, value in dispatch_record.items()
        if key not in _SELF_DECLARED_PAYLOAD_KEYS
    }


def _axis_value(recorded: Mapping[str, Any], axis: str) -> str:
    snake = "".join(
        "_" + ch.lower() if ch.isupper() else ch for ch in axis
    ).lstrip("_")
    raw = recorded.get(axis)
    if raw is None:
        raw = recorded.get(snake)
    if raw is None or raw == "":
        return _CORRELATED_UNKNOWN
    text = str(raw).strip()
    if not text or text.lower() in {"unknown", "__unknown__"}:
        return _CORRELATED_UNKNOWN
    return text


def judgment_vote_signature(dispatch_record: Mapping[str, Any]) -> tuple[str, ...]:
    """Build a five-axis independence signature from dispatcher-recorded fields."""
    recorded = _recorded_dispatch(dispatch_record)
    return tuple(_axis_value(recorded, axis) for axis in JUDGMENT_INDEPENDENCE_AXES)


def is_non_model_judgment_vote(dispatch_record: Mapping[str, Any]) -> bool:
    """True when persona, prompt, context, or evidence axes are recorded."""
    recorded = _recorded_dispatch(dispatch_record)
    for axis in JUDGMENT_INDEPENDENCE_AXES[1:]:
        if _axis_value(recorded, axis) != _CORRELATED_UNKNOWN:
            return True
    return False


def count_independent_judgment_votes(
    results: Iterable[VerifierResult],
    *,
    passed_only: bool = False,
) -> int:
    """Count distinct judgment votes; mechanical scanners never contribute."""
    signatures: set[tuple[str, ...]] = set()
    for result in results:
        if result.kind != VerifierKind.JUDGMENT:
            continue
        if passed_only and not result.passed:
            continue
        if result.dispatch_record is None:
            signatures.add(tuple(_CORRELATED_UNKNOWN for _ in JUDGMENT_INDEPENDENCE_AXES))
            continue
        signatures.add(judgment_vote_signature(result.dispatch_record))
    return len(signatures)


def _judgment_quorum_satisfied(
    judgments: list[VerifierResult],
    *,
    judgment_quorum: int,
) -> tuple[bool, str]:
    passing = [result for result in judgments if result.passed]
    if judgment_quorum < 1:
        return True, ""
    if not passing:
        return False, "judgment quorum not reached"
    independent = count_independent_judgment_votes(passing, passed_only=True)
    if independent < judgment_quorum:
        return False, "judgment quorum not reached"
    if not any(
        result.dispatch_record is not None
        and is_non_model_judgment_vote(result.dispatch_record)
        for result in passing
    ):
        return False, "judgment quorum requires at least one non-model vote"
    return True, ""


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
    quorum_ok, quorum_reason = _judgment_quorum_satisfied(
        judgments,
        judgment_quorum=judgment_quorum,
    )
    if not quorum_ok:
        return VerificationVerdict(
            False, VerifierKind.JUDGMENT, ordered, quorum_reason
        )
    synthesis = grouped[VerifierKind.SYNTHESIS]
    if any(not result.passed for result in synthesis):
        return VerificationVerdict(
            False, VerifierKind.SYNTHESIS, ordered, "synthesis failed"
        )
    return VerificationVerdict(True, None, ordered, "all applicable verifier tiers passed")
