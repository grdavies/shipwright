#!/usr/bin/env python3
"""Learning consumers with exogenous outcome gates (PRD 272 R13).

Advisory snapshot cache invalidation contract (PRD 351 R15 / TR2)
-----------------------------------------------------------------
``get_current_advisory`` reads from an **immutable** module-level snapshot.
Callers never mutate the snapshot in place. To publish new recommendations,
invoke ``replace_advisory_snapshot`` (or ``clear_advisory_snapshot``), which
swaps the entire mapping under a lock. Concurrent readers may observe either
the previous or the new snapshot — never a partially updated map.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from graph.learning_store import LearningEvent, LearningStore, validate_admission
from model_policy_lib import ModelPolicy, TierRecommendation, recommend_implement_tier
from workflow_intelligence import AdvisoryRecommendation

EXOGENOUS_SIGNAL_KEYS = frozenset(
    {
        "postMergeRevertRate",
        "hotfixWithinNDaysRate",
        "escapedDefectRate",
        "reopenedGapUnitRate",
    }
)

_SNAPSHOT_LOCK = threading.RLock()
_ADVISORY_SNAPSHOT: Mapping[str, AdvisoryRecommendation] = MappingProxyType({})


def replace_advisory_snapshot(
    entries: Mapping[str, AdvisoryRecommendation],
) -> None:
    """Atomically replace the advisory snapshot (immutable publish; TR2)."""
    global _ADVISORY_SNAPSHOT
    frozen = MappingProxyType(dict(entries))
    with _SNAPSHOT_LOCK:
        _ADVISORY_SNAPSHOT = frozen


def clear_advisory_snapshot() -> None:
    """Clear the advisory snapshot (test/helper)."""
    replace_advisory_snapshot({})


def get_current_advisory(
    task_type: str,
    dimension_record: dict[str, Any],
) -> AdvisoryRecommendation | None:
    """Return the current advisory recommendation or None (R15).

    No side effects. Thread-safe via immutable snapshot cache. Returns ``None``
    for all no-data paths (never raises for missing data).
    """
    del dimension_record  # reserved for future dimension-scoped lookup
    key = str(task_type or "").strip()
    if not key:
        return None
    with _SNAPSHOT_LOCK:
        snapshot = _ADVISORY_SNAPSHOT
    return snapshot.get(key)


@dataclass(frozen=True)
class CohortOutcomeStats:
    """Aggregated cohort outcomes for tier recommendation."""

    ready_without_rework_rate: float
    exogenous: dict[str, float]
    sample_size: int
    hold_detection_config: str


def _exogenous_non_regressing(
    current: Mapping[str, float],
    baseline: Mapping[str, float],
) -> bool:
    for key in EXOGENOUS_SIGNAL_KEYS:
        if key not in current or key not in baseline:
            continue
        if current[key] > baseline[key]:
            return False
    return True


def aggregate_cohort_stats(
    events: tuple[LearningEvent, ...],
    *,
    hold_detection_config: str,
) -> CohortOutcomeStats:
    if not events:
        return CohortOutcomeStats(
            ready_without_rework_rate=0.0,
            exogenous={},
            sample_size=0,
            hold_detection_config=hold_detection_config,
        )
    rwr_hits = 0
    exogenous_totals: dict[str, float] = {key: 0.0 for key in EXOGENOUS_SIGNAL_KEYS}
    exogenous_counts: dict[str, int] = {key: 0 for key in EXOGENOUS_SIGNAL_KEYS}
    for event in events:
        outcomes = event.outcomes
        if outcomes.get("readyWithoutRework"):
            rwr_hits += 1
        exogenous = outcomes.get("exogenous") or {}
        if isinstance(exogenous, dict):
            for key in EXOGENOUS_SIGNAL_KEYS:
                if key in exogenous and exogenous[key] is not None:
                    exogenous_totals[key] += float(exogenous[key])
                    exogenous_counts[key] += 1
    averaged = {
        key: exogenous_totals[key] / exogenous_counts[key]
        for key in EXOGENOUS_SIGNAL_KEYS
        if exogenous_counts[key] > 0
    }
    return CohortOutcomeStats(
        ready_without_rework_rate=rwr_hits / len(events),
        exogenous=averaged,
        sample_size=len(events),
        hold_detection_config=hold_detection_config,
    )


def recommend_tier_from_cohort(
    *,
    current_tier: str,
    stats: CohortOutcomeStats,
    baseline_exogenous: Mapping[str, float],
    policy: ModelPolicy,
    allowed_tiers: tuple[str, ...],
    proposed_tier: str | None = None,
) -> TierRecommendation:
    """Recommend implement tier with exogenous gate; RWR alone cannot cut depth (R13)."""
    target = proposed_tier or current_tier
    current_rank = policy.tier_rank(current_tier)
    target_rank = policy.tier_rank(target)
    if current_rank is None or target_rank is None:
        return TierRecommendation(
            recommended_tier=current_tier,
            blocked=True,
            reason="unknown-tier",
        )

    if target_rank < current_rank:
        if not stats.exogenous:
            return TierRecommendation(
                recommended_tier=current_tier,
                blocked=True,
                reason="exogenous-signal-required",
            )
        if not _exogenous_non_regressing(stats.exogenous, baseline_exogenous):
            return TierRecommendation(
                recommended_tier=current_tier,
                blocked=True,
                reason="exogenous-regression",
            )
        if stats.ready_without_rework_rate >= 1.0 and not stats.exogenous:
            return TierRecommendation(
                recommended_tier=current_tier,
                blocked=True,
                reason="rwr-alone-insufficient",
            )

    return recommend_implement_tier(
        current_tier,
        proposed_tier=target,
        ready_without_rework_rate=stats.ready_without_rework_rate,
        exogenous=stats.exogenous,
        baseline_exogenous=baseline_exogenous,
        policy=policy,
        allowed_tiers=allowed_tiers,
        hold_detection_config=stats.hold_detection_config,
    )


def routing_cohort_stats(
    store: LearningStore,
    *,
    dimensions: Mapping[str, Any] | None = None,
    hold_detection_config: str,
) -> CohortOutcomeStats:
    events = store.query_routing_cohort(dimensions=dimensions)
    for event in events:
        validate_admission(
            provenance=event.provenance,
            terminally_settled=event.terminally_settled,
            kernel_compiled=event.kernel_compiled,
            for_routing_cohort=True,
        )
    return aggregate_cohort_stats(events, hold_detection_config=hold_detection_config)
