#!/usr/bin/env python3
"""Cost-per-surviving-finding reporter (PRD 273 R4/R14)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

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
