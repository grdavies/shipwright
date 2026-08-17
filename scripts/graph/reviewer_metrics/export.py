#!/usr/bin/env python3
"""Metadata-only query/export for reviewer metrics (PRD 273 R11)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from graph.reviewer_metrics.independence import (
    ReviewerAxisIdentity,
    independence_warnings,
    score_independence,
)
from graph.reviewer_metrics.ranking import MIN_RANKING_N, RankingVerdict, rank_reviewers
from graph.reviewer_metrics.elo import ReviewerRating


class ExportVerdict(str, Enum):
    OK = "ok"
    UNKNOWN = "unknown"


FORBIDDEN_EXPORT_KEYS = frozenset(
    {
        "transcript",
        "findingBody",
        "findingText",
        "body",
        "prompt",
        "promptText",
        "patch",
        "patchDiff",
        "secret",
        "secrets",
        "rawContent",
        "content",
        "message",
        "messages",
        "diff",
        "snippet",
    }
)


@dataclass(frozen=True)
class ExportPair:
    reviewer_id: str
    rating: float
    rank: int


@dataclass(frozen=True)
class ExportReport:
    top: tuple[ExportPair, ...]
    bottom: tuple[ExportPair, ...]
    independence_warnings: tuple[str, ...]
    sample_size: int
    verdict: ExportVerdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "top": [
                {"reviewerId": item.reviewer_id, "rating": item.rating, "rank": item.rank}
                for item in self.top
            ],
            "bottom": [
                {"reviewerId": item.reviewer_id, "rating": item.rating, "rank": item.rank}
                for item in self.bottom
            ],
            "independenceWarnings": list(self.independence_warnings),
            "sampleSize": self.sample_size,
            "verdict": self.verdict.value,
        }


def _assert_metadata_only(payload: Mapping[str, Any]) -> None:
    for key in payload:
        lowered = str(key).lower()
        if key in FORBIDDEN_EXPORT_KEYS or lowered in FORBIDDEN_EXPORT_KEYS:
            raise ValueError(f"forbidden export field: {key}")


def build_export_report(
    ratings: Sequence[ReviewerRating],
    identities: Sequence[ReviewerAxisIdentity],
    *,
    top_n: int = 3,
    bottom_n: int = 3,
    min_n: int = MIN_RANKING_N,
) -> ExportReport:
    """Top/bottom pairs plus independence warnings — metadata only."""
    ranking = rank_reviewers(ratings, min_n=min_n)
    independence = score_independence(identities)
    warnings = independence_warnings(independence)

    if ranking.verdict == RankingVerdict.UNKNOWN or ranking.suppressed:
        report = ExportReport((), (), warnings, ranking.sample_size, ExportVerdict.UNKNOWN)
        _assert_metadata_only(report.to_dict())
        return report

    ordered = list(ranking.ranked)
    top_count = max(0, min(top_n, len(ordered)))
    bottom_count = max(0, min(bottom_n, len(ordered)))
    top = tuple(
        ExportPair(item.reviewer_id, item.rating, item.rank) for item in ordered[:top_count]
    )
    bottom = tuple(
        ExportPair(item.reviewer_id, item.rating, item.rank)
        for item in reversed(ordered[-bottom_count:])
    )
    report = ExportReport(top, bottom, warnings, ranking.sample_size, ExportVerdict.OK)
    _assert_metadata_only(report.to_dict())
    return report
