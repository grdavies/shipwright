#!/usr/bin/env python3
"""Calibration reporter — confidence vs exogenous TP rates (PRD 273 R3)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from graph.reviewer_metrics.surviving import CouplingEvidence, SurvivingVerdict, classify_surviving


class CalibrationVerdict(str, Enum):
    OK = "ok"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FindingCalibrationInput:
    finding_id: str
    confidence: float
    attribution_window: str
    evidence: Sequence[CouplingEvidence]


@dataclass(frozen=True)
class CalibrationBucket:
    confidence_floor: float
    confidence_ceiling: float
    labeled_count: int
    exogenous_tp_count: int
    exogenous_tp_rate: float | None


@dataclass(frozen=True)
class WindowCalibrationReport:
    attribution_window: str
    buckets: tuple[CalibrationBucket, ...]
    labeled_count: int
    exogenous_tp_count: int
    exogenous_tp_rate: float | None
    verdict: CalibrationVerdict


def _clamp_confidence(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _is_exogenous_true_positive(evidence: Sequence[CouplingEvidence]) -> bool | None:
    verdict = classify_surviving(evidence)
    if verdict == SurvivingVerdict.CENSORED:
        return None
    if verdict == SurvivingVerdict.SURVIVING:
        return True
    if verdict in {SurvivingVerdict.REJECTED, SurvivingVerdict.UNKNOWN}:
        return False
    return None


def _bucket_index(confidence: float, *, bucket_size: float) -> int:
    if bucket_size <= 0:
        raise ValueError("bucket_size must be positive")
    clamped = _clamp_confidence(confidence)
    index = int(clamped / bucket_size)
    max_index = int(1.0 / bucket_size) - 1
    return min(index, max_index)


def report_calibration_for_window(
    findings: Sequence[FindingCalibrationInput],
    *,
    attribution_window: str,
    bucket_size: float = 0.25,
) -> WindowCalibrationReport:
    window_findings = [
        item for item in findings if item.attribution_window == attribution_window
    ]
    bucket_count = max(1, int(round(1.0 / bucket_size)))
    buckets: list[CalibrationBucket] = []
    for index in range(bucket_count):
        floor = index * bucket_size
        ceiling = min(1.0, floor + bucket_size)
        buckets.append(
            CalibrationBucket(
                confidence_floor=floor,
                confidence_ceiling=ceiling,
                labeled_count=0,
                exogenous_tp_count=0,
                exogenous_tp_rate=None,
            )
        )

    labeled_count = 0
    exogenous_tp_count = 0
    for finding in window_findings:
        tp = _is_exogenous_true_positive(finding.evidence)
        if tp is None:
            continue
        labeled_count += 1
        if tp:
            exogenous_tp_count += 1
        index = _bucket_index(finding.confidence, bucket_size=bucket_size)
        bucket = buckets[index]
        labeled = bucket.labeled_count + 1
        tp_count = bucket.exogenous_tp_count + (1 if tp else 0)
        buckets[index] = CalibrationBucket(
            confidence_floor=bucket.confidence_floor,
            confidence_ceiling=bucket.confidence_ceiling,
            labeled_count=labeled,
            exogenous_tp_count=tp_count,
            exogenous_tp_rate=tp_count / labeled if labeled else None,
        )

    overall_rate = (
        exogenous_tp_count / labeled_count if labeled_count else None
    )
    verdict = CalibrationVerdict.OK if labeled_count else CalibrationVerdict.UNKNOWN
    return WindowCalibrationReport(
        attribution_window=attribution_window,
        buckets=tuple(buckets),
        labeled_count=labeled_count,
        exogenous_tp_count=exogenous_tp_count,
        exogenous_tp_rate=overall_rate,
        verdict=verdict,
    )


def report_calibration(
    findings: Sequence[FindingCalibrationInput],
    *,
    windows: Sequence[str] | None = None,
    bucket_size: float = 0.25,
) -> tuple[WindowCalibrationReport, ...]:
    if windows is None:
        windows = tuple(sorted({item.attribution_window for item in findings}))
    return tuple(
        report_calibration_for_window(
            findings,
            attribution_window=window,
            bucket_size=bucket_size,
        )
        for window in windows
    )
