#!/usr/bin/env python3
"""Decision-log acknowledgement fixtures for PRD 273 (D1–D7, R9)."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
_REPO = _SCRIPTS.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.reviewer_metrics import elo as elo_module  # noqa: E402
from graph.reviewer_metrics import ranking as ranking_module  # noqa: E402
from graph.reviewer_metrics.cohort import CohortIdentity  # noqa: E402
from graph.reviewer_metrics.elo import (  # noqa: E402
    ContestOutcome,
    PairwiseContest,
    ReviewerRating,
    initial_ratings,
    update_ratings_for_contest,
)
from graph.reviewer_metrics.ranking import MIN_RANKING_N  # noqa: E402
from graph.reviewer_metrics.surviving import (  # noqa: E402
    SurvivingVerdict,
    censored_not_elo_loss,
    classify_surviving,
)


def _read_repo_file(rel: str) -> str:
    return (_REPO / rel).read_text(encoding="utf-8")


def test_docs_restate_np1_np3_boundaries() -> None:
    layout = _read_repo_file(".shipwright/layout.md")
    for phrase in (
        "NP-1",
        "no promotion inflation",
        "NP-3",
        "no closed-loop optimization",
        "PRD 272",
        ".cursor/sw-learning-store/",
        "ELO_GATING_ENABLED",
        "RANKING_GATING_ENABLED",
    ):
        assert phrase in layout


def test_decision_stance_1_4_5_encoded() -> None:
    """Stance 1 (offline/advisory), 4 (learning-store authority), 5 (non-gating)."""
    layout = _read_repo_file(".shipwright/layout.md")
    workflows = _read_repo_file("docs/guides/workflows.md")
    assert "advisory-only" in layout.lower() or "advisory only" in layout.lower()
    assert "non-gating" in layout.lower() or "non-gating" in workflows.lower()
    assert elo_module.ELO_GATING_ENABLED is False
    assert ranking_module.RANKING_GATING_ENABLED is False
    assert "sw-learning-store" in layout


def test_decision_reject_closed_loop_np1() -> None:
    layout = _read_repo_file(".shipwright/layout.md")
    assert "closed-loop" in layout.lower()
    assert "no promotion" in layout.lower() or "NP-1" in layout
    promotion_test = _REPO / "scripts/unit_tests/graph/test_reviewer_metrics_no_promotion.py"
    assert promotion_test.is_file()


def test_decision_advisory_picker_deferred() -> None:
    review_cmd = _read_repo_file("core/commands/sw-review.md")
    assert "advisory picker is deferred" in review_cmd.lower()
    assert "code-review-select.py" in review_cmd


def test_decision_elo_pairwise_draws_noop() -> None:
    review_cmd = _read_repo_file("core/commands/sw-review.md")
    assert "same-cohort pairwise" in review_cmd.lower()
    assert "draw" in review_cmd.lower()

    cohort = CohortIdentity(
        persona_version="p1",
        prompt_version="pr1",
        model_version="m1",
        schema_version=1,
        policy_version="pol1",
    )
    ratings = initial_ratings(["alpha", "beta"], cohort)
    contest = PairwiseContest("alpha", "beta", ContestOutcome.DRAW, cohort)
    updated = update_ratings_for_contest(ratings, contest)
    assert updated["alpha"].rating == ratings["alpha"].rating
    assert updated["beta"].rating == ratings["beta"].rating


def test_decision_n_ge_10_documented() -> None:
    config = _read_repo_file("docs/guides/configuration.md")
    assert "MIN_RANKING_N" in config
    assert str(MIN_RANKING_N) in config
    assert "unknown" in config.lower()


def test_decision_unlabeled_censored_documented() -> None:
    config = _read_repo_file("docs/guides/configuration.md")
    assert "censored" in config.lower()
    assert "Elo losses" in config or "elo losses" in config.lower()
    assert classify_surviving(()) == SurvivingVerdict.CENSORED
    assert censored_not_elo_loss(SurvivingVerdict.CENSORED)


def test_decision_learning_store_sole_authority() -> None:
    doc_review = _read_repo_file("core/commands/sw-doc-review.md")
    assert "sw-learning-store" in doc_review
    assert "sole v1 authority" in doc_review.lower()
    adapter = _read_repo_file("scripts/graph/reviewer_metrics/store_adapter.py")
    assert "sole v1 authority" in adapter.lower()
