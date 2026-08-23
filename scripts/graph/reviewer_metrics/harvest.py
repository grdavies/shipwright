#!/usr/bin/env python3
"""Reviewer effectiveness harvest from classified findings (PRD 326 R16)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from graph.reviewer_metrics.calibration import FindingCalibrationInput, report_calibration_for_window
from graph.reviewer_metrics.cohort import CohortIdentity
from graph.reviewer_metrics.elo import (
    EloConfig,
    PairwiseContest,
    contest_from_exogenous_evidence,
    initial_ratings,
    recompute_from_contests,
)
from graph.reviewer_metrics.surviving import SurvivingVerdict, classify_surviving

HARVEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class HarvestFindingInput:
    finding_id: str
    run_id: str
    reviewer_id: str
    confidence: float
    attribution_window: str
    evidence: Sequence[Any]


@dataclass(frozen=True)
class HarvestReviewerScore:
    reviewer_id: str
    rating: float
    calibration_error: float | None
    labeled_count: int
    surviving_count: int
    contributing_finding_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "reviewerId": self.reviewer_id,
            "rating": self.rating,
            "calibrationError": self.calibration_error,
            "labeledCount": self.labeled_count,
            "survivingCount": self.surviving_count,
            "contributingFindingIds": list(self.contributing_finding_ids),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HarvestReviewerScore:
        return cls(
            reviewer_id=str(payload["reviewerId"]),
            rating=float(payload["rating"]),
            calibration_error=(
                float(payload["calibrationError"])
                if payload.get("calibrationError") is not None
                else None
            ),
            labeled_count=int(payload.get("labeledCount", 0)),
            surviving_count=int(payload.get("survivingCount", 0)),
            contributing_finding_ids=tuple(
                str(item) for item in payload.get("contributingFindingIds") or ()
            ),
        )


@dataclass(frozen=True)
class HarvestRecord:
    schema_version: int
    harvested_at: str
    reviewers: tuple[HarvestReviewerScore, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "harvestedAt": self.harvested_at,
            "reviewers": [item.to_dict() for item in self.reviewers],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> HarvestRecord:
        version = int(payload.get("schemaVersion", HARVEST_SCHEMA_VERSION))
        reviewers = tuple(
            HarvestReviewerScore.from_dict(item)
            for item in payload.get("reviewers") or ()
        )
        return cls(
            schema_version=version,
            harvested_at=str(payload.get("harvestedAt", "")),
            reviewers=reviewers,
        )


def _labeled_findings(
    findings: Sequence[HarvestFindingInput],
) -> tuple[HarvestFindingInput, ...]:
    labeled: list[HarvestFindingInput] = []
    for finding in findings:
        if classify_surviving(finding.evidence) == SurvivingVerdict.CENSORED:
            continue
        labeled.append(finding)
    return tuple(labeled)


def _build_contests(
    findings: Sequence[HarvestFindingInput],
    *,
    cohort: CohortIdentity,
) -> tuple[PairwiseContest, ...]:
    by_run: dict[str, list[HarvestFindingInput]] = {}
    for finding in findings:
        by_run.setdefault(finding.run_id, []).append(finding)
    contests: list[PairwiseContest] = []
    for run_findings in by_run.values():
        for left_index, left in enumerate(run_findings):
            for right in run_findings[left_index + 1 :]:
                if left.reviewer_id == right.reviewer_id:
                    continue
                contest = contest_from_exogenous_evidence(
                    left.reviewer_id,
                    right.reviewer_id,
                    cohort=cohort,
                    evidence_a=left.evidence,
                    evidence_b=right.evidence,
                )
                if contest is not None:
                    contests.append(contest)
    return tuple(contests)


def _calibration_error_for_reviewer(
    findings: Sequence[HarvestFindingInput],
    *,
    reviewer_id: str,
) -> float | None:
    reviewer_findings = [item for item in findings if item.reviewer_id == reviewer_id]
    if not reviewer_findings:
        return None
    window = reviewer_findings[0].attribution_window
    calibration_inputs = tuple(
        FindingCalibrationInput(
            finding_id=item.finding_id,
            confidence=item.confidence,
            attribution_window=item.attribution_window,
            evidence=item.evidence,
        )
        for item in reviewer_findings
    )
    report = report_calibration_for_window(calibration_inputs, attribution_window=window)
    if report.labeled_count == 0:
        return None
    errors: list[float] = []
    for item in reviewer_findings:
        verdict = classify_surviving(item.evidence)
        if verdict == SurvivingVerdict.CENSORED:
            continue
        expected = 1.0 if verdict == SurvivingVerdict.SURVIVING else 0.0
        errors.append(abs(item.confidence - expected))
    if not errors:
        return None
    return sum(errors) / len(errors)


def harvest_reviewers(
    findings: Sequence[HarvestFindingInput],
    *,
    cohort: CohortIdentity,
    harvested_at: str,
    config: EloConfig | None = None,
) -> HarvestRecord:
    """Harvest per-reviewer effectiveness; censored findings are excluded."""
    labeled = _labeled_findings(findings)
    reviewer_ids = sorted({item.reviewer_id for item in labeled})
    contests = _build_contests(labeled, cohort=cohort)
    ratings = recompute_from_contests(contests, reviewer_ids, cohort, config=config)
    if not ratings and reviewer_ids:
        ratings = initial_ratings(reviewer_ids, cohort, config=config)

    scores: list[HarvestReviewerScore] = []
    for reviewer_id in reviewer_ids:
        reviewer_findings = [item for item in labeled if item.reviewer_id == reviewer_id]
        surviving_count = sum(
            1
            for item in reviewer_findings
            if classify_surviving(item.evidence) == SurvivingVerdict.SURVIVING
        )
        scores.append(
            HarvestReviewerScore(
                reviewer_id=reviewer_id,
                rating=ratings[reviewer_id].rating if reviewer_id in ratings else 0.0,
                calibration_error=_calibration_error_for_reviewer(
                    labeled,
                    reviewer_id=reviewer_id,
                ),
                labeled_count=len(reviewer_findings),
                surviving_count=surviving_count,
                contributing_finding_ids=tuple(
                    sorted(item.finding_id for item in reviewer_findings)
                ),
            )
        )

    ordered = sorted(
        scores,
        key=lambda item: (
            -item.rating,
            item.calibration_error if item.calibration_error is not None else 0.0,
            -item.surviving_count,
            item.reviewer_id,
        ),
    )
    return HarvestRecord(
        schema_version=HARVEST_SCHEMA_VERSION,
        harvested_at=harvested_at,
        reviewers=tuple(ordered),
    )


def harvest_score_map(record: HarvestRecord) -> dict[str, HarvestReviewerScore]:
    return {item.reviewer_id: item for item in record.reviewers}
