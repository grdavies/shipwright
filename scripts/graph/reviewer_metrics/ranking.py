#!/usr/bin/env python3
"""Ranking report with N>=10 gate (PRD 273 R22)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Sequence

from graph.reviewer_metrics.elo import ReviewerRating

MIN_RANKING_N = 10
RANKING_GATING_ENABLED = False
SELECTION_FLOOR_REASON = "selection-floor"


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


class SelectionFloorError(RuntimeError):
    """Raised when bounded selection would starve review."""


@dataclass(frozen=True)
class BoundedSelectionResult:
    selected: tuple[str, ...]
    verdict: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"verdict": self.verdict, "selected": list(self.selected)}
        if self.reason:
            payload["reason"] = self.reason
        return payload


def selection_floor_failure(reason: str = SELECTION_FLOOR_REASON) -> SelectionFloorError:
    return SelectionFloorError(reason)


def apply_bounded_selection(
    candidates: Sequence[str],
    *,
    max_personas: int,
    min_personas: int,
) -> BoundedSelectionResult:
    """Truncate ranked candidates without dropping below minPersonas."""
    ordered = tuple(candidates)
    if not ordered:
        return BoundedSelectionResult((), "fail", SELECTION_FLOOR_REASON)
    if min_personas < 1:
        raise ValueError("min_personas must be >= 1")
    if max_personas < min_personas:
        raise ValueError("max_personas must be >= min_personas")
    keep = min(len(ordered), max_personas)
    if keep < min_personas:
        return BoundedSelectionResult((), "fail", SELECTION_FLOOR_REASON)
    selected = ordered[:keep]
    if len(selected) < min_personas:
        return BoundedSelectionResult((), "fail", SELECTION_FLOOR_REASON)
    return BoundedSelectionResult(selected, "ok")
