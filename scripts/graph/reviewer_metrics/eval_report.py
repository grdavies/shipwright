#!/usr/bin/env python3
"""Offline eval uncertainty surface (PRD 273 R17)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from graph.reviewer_metrics.calibration import (
    FindingCalibrationInput,
    report_calibration,
)
from graph.reviewer_metrics.surviving import CouplingEvidence, SurvivingVerdict, classify_surviving


class EvalVerdict(str, Enum):
    OK = "ok"
    UNKNOWN = "unknown"


DEFAULT_MIN_EVIDENCE = 5


@dataclass(frozen=True)
class EvalInput:
    finding_id: str
    confidence: float
    attribution_window: str
    evidence: Sequence[CouplingEvidence]
    rank: int | None = None


@dataclass(frozen=True)
class EvalUncertaintyReport:
    sample_size: int
    labeled_count: int
    label_coverage: float | None
    unresolved_rate: float | None
    calibration_error: float | None
    ranking_stability: float | None
    verdict: EvalVerdict


def _labeled(evidence: Sequence[CouplingEvidence]) -> bool:
    return bool(evidence) and any(item.labeled for item in evidence)


def _unresolved(evidence: Sequence[CouplingEvidence]) -> bool:
    verdict = classify_surviving(evidence)
    return verdict in {SurvivingVerdict.UNKNOWN, SurvivingVerdict.CENSORED}


def _mean_calibration_error(findings: Sequence[FindingCalibrationInput]) -> float | None:
    reports = report_calibration(findings)
    errors: list[float] = []
    for report in reports:
        if report.verdict != report.verdict.OK or report.exogenous_tp_rate is None:
            continue
        for finding in findings:
            if finding.attribution_window != report.attribution_window:
                continue
            tp = classify_surviving(finding.evidence)
            if tp == SurvivingVerdict.CENSORED:
                continue
            expected = 1.0 if tp == SurvivingVerdict.SURVIVING else 0.0
            errors.append(abs(finding.confidence - expected))
    if not errors:
        return None
    return sum(errors) / len(errors)


def _ranking_stability(findings: Sequence[EvalInput]) -> float | None:
    ranked = [item for item in findings if item.rank is not None]
    if len(ranked) < 2:
        return None
    ordered = sorted(ranked, key=lambda item: item.rank or 0)
    stable_pairs = 0
    total_pairs = 0
    for left in range(len(ordered) - 1):
        for right in range(left + 1, len(ordered)):
            total_pairs += 1
            left_conf = ordered[left].confidence
            right_conf = ordered[right].confidence
            if left_conf == right_conf:
                stable_pairs += 1
            elif (left_conf > right_conf) == (
                (ordered[left].rank or 0) < (ordered[right].rank or 0)
            ):
                stable_pairs += 1
    return stable_pairs / total_pairs if total_pairs else None


def report_eval_uncertainty(
    findings: Sequence[EvalInput],
    *,
    min_evidence: int = DEFAULT_MIN_EVIDENCE,
) -> EvalUncertaintyReport:
    sample_size = len(findings)
    labeled = [item for item in findings if _labeled(item.evidence)]
    labeled_count = len(labeled)
    unresolved = [item for item in findings if _unresolved(item.evidence)]

    if sample_size < min_evidence or labeled_count == 0:
        return EvalUncertaintyReport(
            sample_size=sample_size,
            labeled_count=labeled_count,
            label_coverage=None,
            unresolved_rate=None,
            calibration_error=None,
            ranking_stability=None,
            verdict=EvalVerdict.UNKNOWN,
        )

    calibration_inputs = tuple(
        FindingCalibrationInput(
            finding_id=item.finding_id,
            confidence=item.confidence,
            attribution_window=item.attribution_window,
            evidence=item.evidence,
        )
        for item in findings
    )
    return EvalUncertaintyReport(
        sample_size=sample_size,
        labeled_count=labeled_count,
        label_coverage=labeled_count / sample_size,
        unresolved_rate=len(unresolved) / sample_size,
        calibration_error=_mean_calibration_error(calibration_inputs),
        ranking_stability=_ranking_stability(findings),
        verdict=EvalVerdict.OK,
    )
