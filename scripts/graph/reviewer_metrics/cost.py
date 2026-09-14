#!/usr/bin/env python3
"""Cost-per-surviving-finding reporter (PRD 273 R4/R14)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from graph.reviewer_metrics.surviving import CouplingEvidence, SurvivingVerdict, classify_surviving


class CostProvenance(str, Enum):
    DIRECT = "direct"
    PROXY = "proxy"
    RETRY = "retry"
    CACHE = "cache"


class CostVerdict(str, Enum):
    OK = "ok"
    UNKNOWN = "unknown"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class CostSignal:
    amount: float | None
    provenance: str
    currency: str = "usd"


@dataclass(frozen=True)
class FindingCostInput:
    finding_id: str
    evidence: Sequence[CouplingEvidence]
    costs: Sequence[CostSignal]


@dataclass(frozen=True)
class CostReport:
    total_cost: float | None
    surviving_count: int
    excluded_count: int
    cost_per_surviving: float | None
    provenance_breakdown: dict[str, float]
    verdict: CostVerdict


def _effective_cost(signal: CostSignal) -> float | None:
    if signal.amount is None:
        return None
    if signal.amount < 0:
        return None
    return float(signal.amount)


def _finding_total_cost(costs: Sequence[CostSignal]) -> tuple[float | None, dict[str, float]]:
    breakdown: dict[str, float] = {}
    total = 0.0
    saw_known = False
    for signal in costs:
        amount = _effective_cost(signal)
        if amount is None:
            continue
        saw_known = True
        total += amount
        breakdown[signal.provenance] = breakdown.get(signal.provenance, 0.0) + amount
    if not saw_known:
        return None, breakdown
    return total, breakdown


def report_cost(findings: Sequence[FindingCostInput]) -> CostReport:
    total_cost = 0.0
    surviving_count = 0
    excluded_count = 0
    provenance_breakdown: dict[str, float] = {}
    saw_cost = False

    for finding in findings:
        verdict = classify_surviving(finding.evidence)
        if verdict != SurvivingVerdict.SURVIVING:
            if verdict == SurvivingVerdict.CENSORED:
                excluded_count += 1
            continue
        finding_cost, breakdown = _finding_total_cost(finding.costs)
        if finding_cost is None:
            excluded_count += 1
            continue
        surviving_count += 1
        saw_cost = True
        total_cost += finding_cost
        for provenance, amount in breakdown.items():
            provenance_breakdown[provenance] = (
                provenance_breakdown.get(provenance, 0.0) + amount
            )

    if surviving_count == 0:
        return CostReport(
            total_cost=total_cost if saw_cost else None,
            surviving_count=0,
            excluded_count=excluded_count,
            cost_per_surviving=None,
            provenance_breakdown=provenance_breakdown,
            verdict=CostVerdict.UNKNOWN,
        )

    return CostReport(
        total_cost=total_cost if saw_cost else None,
        surviving_count=surviving_count,
        excluded_count=excluded_count,
        cost_per_surviving=total_cost / surviving_count,
        provenance_breakdown=provenance_breakdown,
        verdict=CostVerdict.OK if saw_cost else CostVerdict.UNKNOWN,
    )


@dataclass(frozen=True)
class CostCeilingResult:
    selected: tuple[str, ...]
    total_cost: float
    verdict: str
    reason: str = ""

    def to_dict(self) -> dict[str, float | str | list[str]]:
        payload: dict[str, float | str | list[str]] = {
            "verdict": self.verdict,
            "selected": list(self.selected),
            "totalCost": self.total_cost,
        }
        if self.reason:
            payload["reason"] = self.reason
        return payload


def enforce_cost_ceiling(
    reviewers: Sequence[str],
    *,
    cost_per_reviewer: Mapping[str, float],
    ceiling: float | None,
    min_personas: int = 1,
    default_unit_cost: float = 1.0,
) -> CostCeilingResult:
    """Drop lowest-priority reviewers until dispatch cost is within ceiling."""
    ordered = tuple(reviewers)
    if ceiling is None or ceiling < 0:
        total = sum(cost_per_reviewer.get(item, default_unit_cost) for item in ordered)
        return CostCeilingResult(ordered, total, CostVerdict.OK.value)
    if not ordered:
        return CostCeilingResult((), 0.0, "fail", "selection-floor")

    selected = list(ordered)
    while selected:
        total = sum(cost_per_reviewer.get(item, default_unit_cost) for item in selected)
        if total <= ceiling:
            if len(selected) < min_personas:
                return CostCeilingResult((), total, "fail", "selection-floor")
            return CostCeilingResult(tuple(selected), total, CostVerdict.OK.value)
        if len(selected) <= min_personas:
            return CostCeilingResult((), total, "fail", "selection-floor")
        selected.pop()
    return CostCeilingResult((), 0.0, "fail", "selection-floor")




class CostConfidence(str, Enum):
    """Confidence marker for cost aggregates (PRD 352 R24)."""

    MEASURED = "measured"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


def classify_cost_confidence(record: Mapping[str, Any]) -> CostConfidence:
    """Classify whether a record's cost is measured, estimated, or unknown."""
    if record.get("cost") is not None:
        return CostConfidence.MEASURED
    tokens_in = record.get("tokens_input", record.get("tokens_in"))
    tokens_out = record.get("tokens_output", record.get("tokens_out"))
    if tokens_in is not None or tokens_out is not None:
        return CostConfidence.ESTIMATED
    return CostConfidence.UNKNOWN


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _record_cost_with_confidence(
    record: Mapping[str, Any],
) -> tuple[float | None, CostConfidence]:
    """Return (cost, confidence). Never coerce unknown costs to 0.0 (R24)."""
    confidence = classify_cost_confidence(record)
    if confidence is CostConfidence.MEASURED:
        return _optional_float(record.get("cost")), confidence
    if confidence is CostConfidence.ESTIMATED:
        tokens_in = _optional_float(record.get("tokens_input", record.get("tokens_in"))) or 0.0
        tokens_out = _optional_float(record.get("tokens_output", record.get("tokens_out"))) or 0.0
        return float(tokens_in + tokens_out), confidence
    return None, CostConfidence.UNKNOWN


def _failed_attempt_cost(
    record: Mapping[str, Any],
    *,
    total_cost: float | None,
) -> tuple[float | None, CostConfidence, bool]:
    """Derive cost_failed_attempts contribution.

    Returns (amount, confidence, excluded). When amount cannot be derived,
    excluded=True documents that failed-attempt cost is omitted from totals (R25).
    """
    raw_failed = record.get("failed_attempt_count")
    if raw_failed is None:
        return None, CostConfidence.UNKNOWN, False
    try:
        failed_count = int(raw_failed)
    except (TypeError, ValueError):
        return None, CostConfidence.UNKNOWN, True
    if failed_count <= 0:
        return 0.0, CostConfidence.MEASURED, False

    explicit = record.get("failed_attempt_cost")
    if explicit is not None:
        amount = _optional_float(explicit)
        if amount is None:
            return None, CostConfidence.UNKNOWN, True
        return amount, CostConfidence.MEASURED, False

    attempts = record.get("attempt_count")
    try:
        attempt_count = int(attempts) if attempts is not None else None
    except (TypeError, ValueError):
        attempt_count = None
    if total_cost is not None and attempt_count and attempt_count > 0:
        return (
            float(total_cost) * (failed_count / attempt_count),
            CostConfidence.ESTIMATED,
            False,
        )
    # Documented exclusion: failed attempts present but not allocatable.
    return None, CostConfidence.UNKNOWN, True


def _merge_confidence(values: list[CostConfidence]) -> CostConfidence:
    if not values:
        return CostConfidence.UNKNOWN
    order = {
        CostConfidence.UNKNOWN: 0,
        CostConfidence.ESTIMATED: 1,
        CostConfidence.MEASURED: 2,
    }
    # Worst confidence wins for an aggregate bucket.
    return min(values, key=lambda item: order[item])


def aggregate(
    records: Sequence[Mapping[str, Any]] | None = None,
    *,
    split_verified: bool = False,
) -> dict[str, Any]:
    """Aggregate attribution costs with confidence markers (PRD 352 R24/R25).

    Emits ``measured`` / ``estimated`` / ``unknown`` markers and never coerces
    unknown costs to ``0.0``. Reads ``failed_attempt_count`` into a
    ``cost_failed_attempts`` bucket; unallocatable failed-attempt costs are
    counted in ``cost_failed_attempts_excluded_count`` (documented exclusion).
    """
    source = list(records or ())
    eligible = [r for r in source if not r.get("telemetry_suspect")]

    known_costs: list[float] = []
    known_confidences: list[CostConfidence] = []
    unknown_count = 0
    failed_costs: list[float] = []
    failed_confidences: list[CostConfidence] = []
    failed_exclusions = 0

    for record in eligible:
        amount, confidence = _record_cost_with_confidence(record)
        if amount is None:
            unknown_count += 1
        else:
            known_costs.append(amount)
            known_confidences.append(confidence)
        failed_amount, failed_confidence, excluded = _failed_attempt_cost(
            record, total_cost=amount
        )
        if excluded:
            failed_exclusions += 1
        elif failed_amount is not None:
            failed_costs.append(failed_amount)
            failed_confidences.append(failed_confidence)

    all_count = len(eligible)
    if known_costs:
        cost_per_task_all: float | None = sum(known_costs) / len(known_costs)
        all_confidence = _merge_confidence(known_confidences)
    else:
        cost_per_task_all = None
        all_confidence = CostConfidence.UNKNOWN

    if failed_costs:
        failed_total: float | None = sum(failed_costs)
        failed_confidence = _merge_confidence(failed_confidences)
    elif failed_exclusions:
        failed_total = None
        failed_confidence = CostConfidence.UNKNOWN
    else:
        failed_total = 0.0
        failed_confidence = CostConfidence.MEASURED

    result: dict[str, Any] = {
        "cost_per_task_all": cost_per_task_all,
        "cost_per_task_all_count": all_count,
        "cost_per_task_all_known_count": len(known_costs),
        "cost_per_task_all_unknown_count": unknown_count,
        "cost_per_task_all_confidence": all_confidence.value,
        "cost_failed_attempts": failed_total,
        "cost_failed_attempts_confidence": failed_confidence.value,
        "cost_failed_attempts_excluded_count": failed_exclusions,
    }

    if not split_verified:
        return result

    verified: list[Mapping[str, Any]] = []
    unverified_exclusions = 0
    for record in eligible:
        verification = record.get("verification_result")
        if verification == "unknown" or verification is None:
            unverified_exclusions += 1
            continue
        if verification == "pass" and record.get("rework_required") is False:
            verified.append(record)

    verified_known: list[float] = []
    verified_confidences: list[CostConfidence] = []
    for record in verified:
        amount, confidence = _record_cost_with_confidence(record)
        if amount is None:
            continue
        verified_known.append(amount)
        verified_confidences.append(confidence)

    verified_count = len(verified)
    if verified_known:
        cost_per_verified: float | None = sum(verified_known) / len(verified_known)
        verified_confidence = _merge_confidence(verified_confidences)
    else:
        cost_per_verified = None
        verified_confidence = CostConfidence.UNKNOWN

    result["cost_per_verified_successful_task"] = cost_per_verified
    result["cost_per_verified_successful_task_count"] = verified_count
    result["cost_per_verified_successful_task_confidence"] = verified_confidence.value
    result["unverified_exclusion_count"] = unverified_exclusions
    return result
