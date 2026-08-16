#!/usr/bin/env python3
"""Surviving-finding classification with exogenous coupling rules (PRD 273 R2/R23)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

EXOGENOUS_MATCH_REASONS = frozenset(
    {
        "exogenous-ci",
        "exogenous-post-merge",
        "exogenous-human",
        "operator-override",
        "late-correction",
    }
)
PEER_ONLY_REASONS = frozenset({"peer-agreement"})


class SurvivingVerdict(str, Enum):
    SURVIVING = "surviving"
    CENSORED = "censored"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CouplingEvidence:
    match_reason: str
    terminal_status: str
    labeled: bool = True

    @property
    def exogenous(self) -> bool:
        return self.match_reason in EXOGENOUS_MATCH_REASONS

    @property
    def peer_only(self) -> bool:
        return self.match_reason in PEER_ONLY_REASONS


def requires_exogenous_coupling(evidence: Sequence[CouplingEvidence]) -> bool:
    """Peer agreement alone cannot establish a surviving finding."""
    if not evidence:
        return False
    if all(item.peer_only for item in evidence):
        return False
    return any(item.exogenous for item in evidence)


def is_unlabeled(evidence: Sequence[CouplingEvidence]) -> bool:
    return not evidence or all(not item.labeled for item in evidence)


def classify_surviving(evidence: Sequence[CouplingEvidence]) -> SurvivingVerdict:
    if is_unlabeled(evidence):
        return SurvivingVerdict.CENSORED
    if any(item.terminal_status == "rejected" for item in evidence if item.labeled):
        return SurvivingVerdict.REJECTED
    if requires_exogenous_coupling(evidence):
        return SurvivingVerdict.SURVIVING
    if any(item.peer_only for item in evidence):
        return SurvivingVerdict.REJECTED
    return SurvivingVerdict.UNKNOWN


def censored_not_elo_loss(verdict: SurvivingVerdict) -> bool:
    """Unlabeled findings are censored — never treated as Elo losses."""
    return verdict == SurvivingVerdict.CENSORED


def censored_not_negative_calibration(verdict: SurvivingVerdict) -> bool:
    return verdict == SurvivingVerdict.CENSORED
