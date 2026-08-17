#!/usr/bin/env python3
"""Pairwise Elo engine for reviewer effectiveness (PRD 273 R6, R21)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from graph.reviewer_metrics.cohort import CohortIdentity, cohort_compatible
from graph.reviewer_metrics.surviving import (
    CouplingEvidence,
    SurvivingVerdict,
    classify_surviving,
)

DEFAULT_K_FACTOR = 32.0
DEFAULT_RATING_FLOOR = 100.0
DEFAULT_RATING_CEILING = 3000.0
DEFAULT_INITIAL_RATING = 1500.0

ELO_GATING_ENABLED = False


class ContestOutcome(str, Enum):
    WIN = "win"
    LOSS = "loss"
    DRAW = "draw"


class EloError(ValueError):
    """Raised when an Elo update violates cohort or contest rules."""


@dataclass(frozen=True)
class EloConfig:
    k_factor: float = DEFAULT_K_FACTOR
    floor: float = DEFAULT_RATING_FLOOR
    ceiling: float = DEFAULT_RATING_CEILING
    initial_rating: float = DEFAULT_INITIAL_RATING


@dataclass(frozen=True)
class ReviewerRating:
    reviewer_id: str
    rating: float
    cohort: CohortIdentity
    contests_played: int = 0


@dataclass(frozen=True)
class PairwiseContest:
    reviewer_a: str
    reviewer_b: str
    outcome: ContestOutcome
    cohort: CohortIdentity
    evidence_a: Sequence[CouplingEvidence] = ()
    evidence_b: Sequence[CouplingEvidence] = ()


@dataclass(frozen=True)
class LateLabelCorrection:
    """Append-only late label correction event (R21)."""

    event_id: str
    finding_id: str
    reviewer_id: str
    opponent_id: str
    prior_outcome: ContestOutcome
    corrected_outcome: ContestOutcome
    cohort: CohortIdentity
    recorded_at: str


def documented_defaults() -> dict[str, float]:
    return {
        "kFactor": DEFAULT_K_FACTOR,
        "floor": DEFAULT_RATING_FLOOR,
        "ceiling": DEFAULT_RATING_CEILING,
        "initialRating": DEFAULT_INITIAL_RATING,
    }


def expected_score(rating: float, opponent_rating: float) -> float:
    return 1.0 / (1.0 + 10 ** ((opponent_rating - rating) / 400.0))


def clamp_rating(rating: float, config: EloConfig) -> float:
    return max(config.floor, min(config.ceiling, rating))


def score_for_outcome(outcome: ContestOutcome) -> float:
    if outcome == ContestOutcome.WIN:
        return 1.0
    if outcome == ContestOutcome.LOSS:
        return 0.0
    if outcome == ContestOutcome.DRAW:
        return 0.5
    raise EloError(f"unknown outcome: {outcome}")


def apply_rating_update(
    rating: float,
    opponent_rating: float,
    score: float,
    *,
    config: EloConfig,
) -> float:
    delta = config.k_factor * (score - expected_score(rating, opponent_rating))
    return clamp_rating(rating + delta, config)


def contest_from_exogenous_evidence(
    reviewer_a: str,
    reviewer_b: str,
    *,
    cohort: CohortIdentity,
    evidence_a: Sequence[CouplingEvidence],
    evidence_b: Sequence[CouplingEvidence],
) -> PairwiseContest | None:
    verdict_a = classify_surviving(evidence_a)
    verdict_b = classify_surviving(evidence_b)
    if verdict_a == SurvivingVerdict.CENSORED or verdict_b == SurvivingVerdict.CENSORED:
        return None
    if verdict_a == SurvivingVerdict.SURVIVING and verdict_b != SurvivingVerdict.SURVIVING:
        return PairwiseContest(
            reviewer_a,
            reviewer_b,
            ContestOutcome.WIN,
            cohort,
            evidence_a,
            evidence_b,
        )
    if verdict_b == SurvivingVerdict.SURVIVING and verdict_a != SurvivingVerdict.SURVIVING:
        return PairwiseContest(
            reviewer_a,
            reviewer_b,
            ContestOutcome.LOSS,
            cohort,
            evidence_a,
            evidence_b,
        )
    return PairwiseContest(
        reviewer_a,
        reviewer_b,
        ContestOutcome.DRAW,
        cohort,
        evidence_a,
        evidence_b,
    )


def update_ratings_for_contest(
    ratings: Mapping[str, ReviewerRating],
    contest: PairwiseContest,
    *,
    config: EloConfig | None = None,
) -> dict[str, ReviewerRating]:
    cfg = config or EloConfig()
    if contest.outcome == ContestOutcome.DRAW:
        return dict(ratings)
    left = ratings.get(contest.reviewer_a)
    right = ratings.get(contest.reviewer_b)
    if left is None or right is None:
        raise EloError("both reviewers must exist in ratings table")
    if not cohort_compatible(left.cohort, contest.cohort) or not cohort_compatible(
        right.cohort, contest.cohort
    ):
        raise EloError("contest cohort must match reviewer cohort")
    if not cohort_compatible(left.cohort, right.cohort):
        raise EloError("pairwise updates require same cohort")

    score_a = score_for_outcome(contest.outcome)
    score_b = 1.0 - score_a
    new_a = apply_rating_update(left.rating, right.rating, score_a, config=cfg)
    new_b = apply_rating_update(right.rating, left.rating, score_b, config=cfg)
    updated = dict(ratings)
    updated[contest.reviewer_a] = ReviewerRating(
        contest.reviewer_a,
        new_a,
        left.cohort,
        left.contests_played + 1,
    )
    updated[contest.reviewer_b] = ReviewerRating(
        contest.reviewer_b,
        new_b,
        right.cohort,
        right.contests_played + 1,
    )
    return updated


def initial_ratings(
    reviewer_ids: Sequence[str],
    cohort: CohortIdentity,
    *,
    config: EloConfig | None = None,
) -> dict[str, ReviewerRating]:
    cfg = config or EloConfig()
    return {
        reviewer_id: ReviewerRating(reviewer_id, cfg.initial_rating, cohort)
        for reviewer_id in reviewer_ids
    }


def recompute_from_contests(
    contests: Sequence[PairwiseContest],
    reviewer_ids: Sequence[str],
    cohort: CohortIdentity,
    *,
    config: EloConfig | None = None,
) -> dict[str, ReviewerRating]:
    ratings = initial_ratings(reviewer_ids, cohort, config=config)
    for contest in contests:
        if contest.outcome == ContestOutcome.DRAW:
            continue
        if not cohort_compatible(contest.cohort, cohort):
            continue
        ratings = update_ratings_for_contest(ratings, contest, config=config)
    return ratings


def apply_late_label_corrections(
    contests: list[PairwiseContest],
    corrections: Sequence[LateLabelCorrection],
) -> list[PairwiseContest]:
    extended = list(contests)
    for correction in corrections:
        extended.append(
            PairwiseContest(
                correction.reviewer_id,
                correction.opponent_id,
                correction.corrected_outcome,
                correction.cohort,
            )
        )
    return extended
