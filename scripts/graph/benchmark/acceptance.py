#!/usr/bin/env python3
"""R24 trace acceptance predicate for benchmark metrics (PRD 272 R18/R24)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class TraceEvidence:
    """Minimal TraceRef surface for benchmark acceptance checks."""

    trace_ref_id: str
    head_sha: str
    verifier_class: str
    verdict: str
    advisory: bool = False

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
    if not evidence.head_sha or evidence.head_sha != current_head_sha:
        return False
    if not evidence.verifier_class:
        return False
    return evidence.verifier_class == required_verifier_class
