#!/usr/bin/env python3
"""R24 trace acceptance predicate for benchmark metrics (PRD 272 R18/R24)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from graph.traceability import build_coverage_edge, evaluate_evidence_predicate


@dataclass(frozen=True)
class TraceEvidence:
    """Benchmark-facing TraceRef surface with explicit verdict."""

    trace_ref_id: str
    head_sha: str
    verifier_class: str
    verdict: str
    advisory: bool = False
    requirement_id: str = "acceptance"

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> TraceEvidence:
        return cls(
            trace_ref_id=str(raw.get("traceRefId") or raw.get("traceRef") or ""),
            head_sha=str(raw.get("headSha") or raw.get("head_sha") or ""),
            verifier_class=str(
                raw.get("verifierClass") or raw.get("verifier_class") or ""
            ),
            verdict=str(raw.get("verdict") or ""),
            advisory=bool(raw.get("advisory")),
            requirement_id=str(
                raw.get("requirementId") or raw.get("requirement_id") or "acceptance"
            ),
        )


def evaluate_trace_acceptance(
    evidence: TraceEvidence,
    *,
    current_head_sha: str,
    required_verifier_class: str,
) -> bool:
    """
    Pass only when the correct verifier class attests pass at the current headSha (R24).
    Advisory evidence never satisfies a blocking acceptance predicate.
    """
    if evidence.advisory:
        return False
    if evidence.verdict != "pass":
        return False
    edge = build_coverage_edge(
        evidence.requirement_id,
        required_verifier_class,
        current_head_sha,
        blocking=True,
    )
    result = evaluate_evidence_predicate(
        edge,
        observed_head_sha=evidence.head_sha,
        observed_verifier_class=evidence.verifier_class,
        current_head_sha=current_head_sha,
    )
    return result.passed
