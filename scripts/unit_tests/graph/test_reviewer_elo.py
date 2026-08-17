#!/usr/bin/env python3
"""Elo ladder tests — pairwise updates and late-label recompute (PRD 273 R6, R21)."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.reviewer_metrics.cohort import (  # noqa: E402
    CohortAction,
    CohortIdentity,
    partition_by_cohort,
    resolve_cohort_transition,
)
from graph.reviewer_metrics.elo import (  # noqa: E402
    ContestOutcome,
    EloConfig,
    LateLabelCorrection,
    PairwiseContest,
    apply_late_label_corrections,
    contest_from_exogenous_evidence,
    documented_defaults,
    initial_ratings,
    recompute_from_contests,
    update_ratings_for_contest,
)
from graph.reviewer_metrics.surviving import CouplingEvidence  # noqa: E402


def _cohort(**overrides: object) -> CohortIdentity:
    base = {
        "persona_version": "persona-v1",
        "prompt_version": "prompt-v1",
        "model_version": "model-v1",
        "schema_version": 1,
        "policy_version": "policy-v1",
    }
    base.update(overrides)
    return CohortIdentity(**base)  # type: ignore[arg-type]


def test_elo_update_from_exogenous_win_loss() -> None:
    defaults = documented_defaults()
    assert defaults["kFactor"] == 32.0
    assert defaults["floor"] == 100.0
    assert defaults["ceiling"] == 3000.0
    assert defaults["initialRating"] == 1500.0

    cohort = _cohort()
    contest = contest_from_exogenous_evidence(
        "reviewer-a",
        "reviewer-b",
        cohort=cohort,
        evidence_a=[CouplingEvidence("exogenous-ci", "confirmed")],
        evidence_b=[CouplingEvidence("exogenous-human", "rejected")],
    )
    assert contest is not None
    assert contest.outcome == ContestOutcome.WIN

    ratings = initial_ratings(["reviewer-a", "reviewer-b"], cohort)
    updated = update_ratings_for_contest(ratings, contest, config=EloConfig(k_factor=32.0))
    assert updated["reviewer-a"].rating > ratings["reviewer-a"].rating
    assert updated["reviewer-b"].rating < ratings["reviewer-b"].rating


def test_elo_pairwise_same_cohort_draws_noop() -> None:
    cohort = _cohort()
    draw = PairwiseContest(
        "reviewer-a",
        "reviewer-b",
        ContestOutcome.DRAW,
        cohort,
    )
    ratings = initial_ratings(["reviewer-a", "reviewer-b"], cohort)
    updated = update_ratings_for_contest(ratings, draw)
    assert updated["reviewer-a"].rating == ratings["reviewer-a"].rating
    assert updated["reviewer-b"].rating == ratings["reviewer-b"].rating


def test_late_label_append_only_recompute() -> None:
    cohort = _cohort()
    base_contests = [
        PairwiseContest(
            "reviewer-a",
            "reviewer-b",
            ContestOutcome.WIN,
            cohort,
        )
    ]
    before = recompute_from_contests(
        base_contests,
        ["reviewer-a", "reviewer-b"],
        cohort,
        config=EloConfig(k_factor=32.0),
    )
    correction = LateLabelCorrection(
        event_id="late-1",
        finding_id="finding-9",
        reviewer_id="reviewer-a",
        opponent_id="reviewer-b",
        prior_outcome=ContestOutcome.WIN,
        corrected_outcome=ContestOutcome.LOSS,
        cohort=cohort,
        recorded_at="2026-08-16T00:00:00Z",
    )
    extended = apply_late_label_corrections(list(base_contests), [correction])
    assert len(extended) == len(base_contests) + 1
    assert extended[0].outcome == ContestOutcome.WIN
    assert extended[-1].outcome == ContestOutcome.LOSS

    after = recompute_from_contests(
        extended,
        ["reviewer-a", "reviewer-b"],
        cohort,
        config=EloConfig(k_factor=32.0),
    )
    assert after["reviewer-a"].rating != before["reviewer-a"].rating
    assert after["reviewer-b"].rating != before["reviewer-b"].rating


def test_cohort_partitions_on_incompatible_versions() -> None:
    left = _cohort(schema_version=1, policy_version="policy-v1")
    right = _cohort(schema_version=2, policy_version="policy-v1")
    partitions = partition_by_cohort((left, right))
    assert len(partitions) == 2
    resolution = resolve_cohort_transition(left, right)
    assert resolution.action == CohortAction.PARTITION

    migrate = resolve_cohort_transition(left, _cohort(prompt_version="prompt-v2"))
    assert migrate.action == CohortAction.MIGRATE
