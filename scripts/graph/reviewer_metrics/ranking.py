#!/usr/bin/env python3
"""Ranking report with N>=10 gate (PRD 273 R22)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from graph.reviewer_metrics.elo import ReviewerRating

MIN_RANKING_N = 10
RANKING_GATING_ENABLED = False


class RankingVerdict(str, Enum):
    OK = "ok"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RankedReviewer:
    reviewer_id: str
    rating: float
    rank: int


@dataclass(frozen=True)
class RankingReport:
    ranked: tuple[RankedReviewer, ...]
    sample_size: int
    min_required: int
    verdict: RankingVerdict
    recommend: bool = False

    @property
    def suppressed(self) -> bool:
        return self.verdict == RankingVerdict.UNKNOWN


def rank_reviewers(
    ratings: Sequence[ReviewerRating],
    *,
    min_n: int = MIN_RANKING_N,
) -> RankingReport:
    sample_size = len(ratings)
    if sample_size < min_n:
        return RankingReport((), sample_size, min_n, RankingVerdict.UNKNOWN, recommend=False)
    ordered = sorted(ratings, key=lambda item: (-item.rating, item.reviewer_id))
    ranked = tuple(
        RankedReviewer(item.reviewer_id, item.rating, index + 1)
        for index, item in enumerate(ordered)
    )
    return RankingReport(ranked, sample_size, min_n, RankingVerdict.OK, recommend=False)
