#!/usr/bin/env python3
"""TraceRef/CoverageEdge evidence predicates for status surfaces (PRD 272 R24)."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

VERIFIER_CLASSES = frozenset(
    {
        "mechanical",
        "human",
        "agent",
        "gate",
        "verifier",
    }
)


@dataclass(frozen=True)
class TraceRef:
    """Stable traceability reference for a requirement ↔ verifier binding."""

    id: str
    requirement_id: str
    verifier_class: str
    head_sha: str
    blocking: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "requirementId": self.requirement_id,
            "verifierClass": self.verifier_class,
            "headSha": self.head_sha,
            "blocking": self.blocking,
        }


@dataclass(frozen=True)
class CoverageEdge:
    """Coverage edge linking a TraceRef to live verifier evidence."""

    trace_ref_id: str
    requirement_id: str
    verifier_class: str
    head_sha: str
    blocking: bool = True
    advisory: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "traceRefId": self.trace_ref_id,
            "requirementId": self.requirement_id,
            "verifierClass": self.verifier_class,
            "headSha": self.head_sha,
            "blocking": self.blocking,
            "advisory": self.advisory,
        }
        return payload


@dataclass(frozen=True)
class EvidencePredicateVerdict:
    """Result of evaluating coverage evidence at the current head."""

    passed: bool
    reason: str
    blocking: bool
    advisory: bool
    trace_ref_id: str
    expected_verifier_class: str
    observed_verifier_class: str | None
    expected_head_sha: str
    observed_head_sha: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "blocking": self.blocking,
            "advisory": self.advisory,
            "traceRefId": self.trace_ref_id,
            "expectedVerifierClass": self.expected_verifier_class,
            "observedVerifierClass": self.observed_verifier_class,
            "expectedHeadSha": self.expected_head_sha,
            "observedHeadSha": self.observed_head_sha,
        }


def stable_trace_ref_id(
    requirement_id: str,
    verifier_class: str,
    *,
    head_sha: str | None = None,
) -> str:
    """Deterministic TraceRef id — stable across surfaces."""
    payload = {
        "requirementId": requirement_id,
        "verifierClass": verifier_class,
        "headSha": head_sha or "",
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"traceref-{digest[:24]}"


def build_trace_ref(
    requirement_id: str,
    verifier_class: str,
    head_sha: str,
    *,
    blocking: bool = True,
) -> TraceRef:
    if verifier_class not in VERIFIER_CLASSES:
        raise ValueError(f"unknown verifier class: {verifier_class}")
    trace_id = stable_trace_ref_id(requirement_id, verifier_class, head_sha=head_sha)
    return TraceRef(
        id=trace_id,
        requirement_id=requirement_id,
        verifier_class=verifier_class,
        head_sha=head_sha,
        blocking=blocking,
    )


def build_coverage_edge(
    requirement_id: str,
    verifier_class: str,
    head_sha: str,
    *,
    blocking: bool = True,
    advisory: bool = False,
) -> CoverageEdge:
    trace_id = stable_trace_ref_id(requirement_id, verifier_class, head_sha=head_sha)
    return CoverageEdge(
        trace_ref_id=trace_id,
        requirement_id=requirement_id,
        verifier_class=verifier_class,
        head_sha=head_sha,
        blocking=blocking,
        advisory=advisory,
    )


def evaluate_evidence_predicate(
    edge: CoverageEdge,
    *,
    observed_head_sha: str | None,
    observed_verifier_class: str | None,
    current_head_sha: str,
) -> EvidencePredicateVerdict:
    """Pass only when the correct-class verifier attests at the current headSha."""
    blocking = edge.blocking and not edge.advisory
    if observed_head_sha is None or observed_verifier_class is None:
        return EvidencePredicateVerdict(
            passed=False,
            reason="missing-evidence",
            blocking=blocking,
            advisory=edge.advisory,
            trace_ref_id=edge.trace_ref_id,
            expected_verifier_class=edge.verifier_class,
            observed_verifier_class=observed_verifier_class,
            expected_head_sha=current_head_sha,
            observed_head_sha=observed_head_sha,
        )
    if observed_head_sha != current_head_sha:
        return EvidencePredicateVerdict(
            passed=False,
            reason="stale-head",
            blocking=blocking,
            advisory=edge.advisory,
            trace_ref_id=edge.trace_ref_id,
            expected_verifier_class=edge.verifier_class,
            observed_verifier_class=observed_verifier_class,
            expected_head_sha=current_head_sha,
            observed_head_sha=observed_head_sha,
        )
    if observed_verifier_class != edge.verifier_class:
        return EvidencePredicateVerdict(
            passed=False,
            reason="wrong-verifier-class",
            blocking=blocking,
            advisory=edge.advisory,
            trace_ref_id=edge.trace_ref_id,
            expected_verifier_class=edge.verifier_class,
            observed_verifier_class=observed_verifier_class,
            expected_head_sha=current_head_sha,
            observed_head_sha=observed_head_sha,
        )
    return EvidencePredicateVerdict(
        passed=True,
        reason="ok",
        blocking=blocking,
        advisory=edge.advisory,
        trace_ref_id=edge.trace_ref_id,
        expected_verifier_class=edge.verifier_class,
        observed_verifier_class=observed_verifier_class,
        expected_head_sha=current_head_sha,
        observed_head_sha=observed_head_sha,
    )


def evaluate_coverage_edges(
    edges: Sequence[CoverageEdge],
    *,
    current_head_sha: str,
    evidence_by_trace_ref: Mapping[str, Mapping[str, Any]],
) -> list[EvidencePredicateVerdict]:
    verdicts: list[EvidencePredicateVerdict] = []
    for edge in edges:
        evidence = evidence_by_trace_ref.get(edge.trace_ref_id) or {}
        verdicts.append(
            evaluate_evidence_predicate(
                edge,
                observed_head_sha=str(evidence.get("headSha") or "") or None,
                observed_verifier_class=str(evidence.get("verifierClass") or "") or None,
                current_head_sha=current_head_sha,
            )
        )
    return verdicts


def blocking_failures(
    verdicts: Sequence[EvidencePredicateVerdict],
) -> list[EvidencePredicateVerdict]:
    return [v for v in verdicts if not v.passed and v.blocking]
