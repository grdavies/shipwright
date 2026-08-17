#!/usr/bin/env python3
"""Surviving-finding coupling and censorship tests (PRD 273 R2/R23)."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.reviewer_metrics.surviving import (  # noqa: E402
    CouplingEvidence,
    SurvivingVerdict,
    censored_not_elo_loss,
    censored_not_negative_calibration,
    classify_surviving,
    requires_exogenous_coupling,
)


def test_surviving_requires_exogenous_not_peer_alone() -> None:
    peer_only = [CouplingEvidence("peer-agreement", "confirmed")]
    assert requires_exogenous_coupling(peer_only) is False
    assert classify_surviving(peer_only) == SurvivingVerdict.REJECTED

    exogenous = [CouplingEvidence("exogenous-ci", "confirmed")]
    assert requires_exogenous_coupling(exogenous) is True
    assert classify_surviving(exogenous) == SurvivingVerdict.SURVIVING


def test_exogenous_human_coupling_accepted() -> None:
    evidence = [CouplingEvidence("exogenous-human", "confirmed")]
    assert classify_surviving(evidence) == SurvivingVerdict.SURVIVING


def test_peer_plus_exogenous_accepted() -> None:
    evidence = [
        CouplingEvidence("peer-agreement", "confirmed"),
        CouplingEvidence("exogenous-post-merge", "confirmed"),
    ]
    assert classify_surviving(evidence) == SurvivingVerdict.SURVIVING


def test_unlabeled_censored_not_elo_loss() -> None:
    verdict = classify_surviving([])
    assert verdict == SurvivingVerdict.CENSORED
    assert censored_not_elo_loss(verdict) is True
    assert censored_not_negative_calibration(verdict) is True


def test_unlabeled_explicit_not_labeled_censored() -> None:
    evidence = [CouplingEvidence("exogenous-ci", "confirmed", labeled=False)]
    verdict = classify_surviving(evidence)
    assert verdict == SurvivingVerdict.CENSORED


def test_rejected_terminal_status() -> None:
    evidence = [CouplingEvidence("exogenous-human", "rejected")]
    assert classify_surviving(evidence) == SurvivingVerdict.REJECTED
