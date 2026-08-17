#!/usr/bin/env python3
"""Non-gating negative suite for Elo ladder (PRD 273 R7, R16)."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.reviewer_metrics import elo as elo_module  # noqa: E402
from graph.reviewer_metrics import ranking as ranking_module  # noqa: E402
from graph.reviewer_metrics.cohort import CohortIdentity  # noqa: E402
from graph.reviewer_metrics.elo import (  # noqa: E402
    ContestOutcome,
    EloConfig,
    PairwiseContest,
    initial_ratings,
    recompute_from_contests,
)
from graph.reviewer_metrics.ranking import MIN_RANKING_N, RankingVerdict, rank_reviewers  # noqa: E402


def _cohort() -> CohortIdentity:
    return CohortIdentity(
        persona_version="persona-v1",
        prompt_version="prompt-v1",
        model_version="model-v1",
        schema_version=1,
        policy_version="policy-v1",
    )


def test_ratings_offline_no_panel_mutation() -> None:
    panel = {
        "core": ["bugbot", "security-review"],
        "specialists": ["thermo-nuclear-code-quality-review"],
        "signals": {"review-panel": True},
    }
    snapshot = copy.deepcopy(panel)
    cohort = _cohort()
    contests = [
        PairwiseContest("bugbot", "security-review", ContestOutcome.WIN, cohort),
    ]
    ratings = recompute_from_contests(
        contests,
        ["bugbot", "security-review"],
        cohort,
        config=EloConfig(k_factor=32.0),
    )
    rank_reviewers(tuple(ratings.values()), min_n=2)
    assert panel == snapshot


def test_elo_gating_false_cannot_authorize_reviewers() -> None:
    assert elo_module.ELO_GATING_ENABLED is False
    assert ranking_module.RANKING_GATING_ENABLED is False

    cohort = _cohort()
    ratings = initial_ratings(["alpha", "beta"], cohort)
    report = rank_reviewers(tuple(ratings.values()))
    assert report.recommend is False
    assert report.verdict == RankingVerdict.UNKNOWN
    assert report.sample_size == 2
    assert report.min_required == MIN_RANKING_N

    many = initial_ratings([f"reviewer-{index}" for index in range(MIN_RANKING_N)], cohort)
    populated = rank_reviewers(tuple(many.values()))
    assert populated.recommend is False
    assert populated.verdict == RankingVerdict.OK
    assert all(not hasattr(item, "authorized") for item in populated.ranked)


def test_elo_cannot_alter_kernel_or_promotion_bindings() -> None:
    forbidden = (
        "authorize",
        "deny",
        "rank_bind",
        "add_reviewer",
        "remove_reviewer",
        "kernel",
        "promotion",
    )
    source = Path(elo_module.__file__).read_text(encoding="utf-8")
    source += Path(ranking_module.__file__).read_text(encoding="utf-8")
    lowered = source.lower()
    for token in forbidden:
        assert token not in lowered
