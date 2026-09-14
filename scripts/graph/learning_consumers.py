#!/usr/bin/env python3
"""Learning consumers with exogenous outcome gates (PRD 272 R13).

Advisory snapshot cache invalidation contract (PRD 351 R15 / TR2)
-----------------------------------------------------------------
``get_current_advisory`` reads from an **immutable** module-level snapshot.
Callers never mutate the snapshot in place. To publish new recommendations,
invoke ``replace_advisory_snapshot`` (or ``clear_advisory_snapshot``), which
swaps the entire mapping under a lock. Concurrent readers may observe either
the previous or the new snapshot — never a partially updated map.

PRD 352 R22/TR6 — durable hydration
------------------------------------
``hydrate_advisory_snapshot_from_store`` loads ``$SW_ADVISORY_STORE/advisory.json``
and publishes via ``replace_advisory_snapshot``. ``get_current_advisory`` lazily
hydrates on miss so fresh processes see durable observations (R26).
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
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

ADVISORY_STORE_ENV = "SW_ADVISORY_STORE"
ADVISORY_STORE_FILENAME = "advisory.json"

_SNAPSHOT_LOCK = threading.RLock()
_ADVISORY_SNAPSHOT: Mapping[str, AdvisoryRecommendation] = MappingProxyType({})
_HYDRATED_FROM_STORE = False


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
    global _HYDRATED_FROM_STORE
    with _SNAPSHOT_LOCK:
        _HYDRATED_FROM_STORE = False
    replace_advisory_snapshot({})


def _utc_now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _looks_like_advisory(payload: Mapping[str, Any]) -> bool:
    return "recommended_model" in payload or "recommendedModel" in payload


def _normalize_advisory(payload: Mapping[str, Any]) -> AdvisoryRecommendation:
    """Normalize durable JSON into AdvisoryRecommendation (fill optional fields)."""
    recommended = payload.get("recommended_model", payload.get("recommendedModel"))
    if recommended is None or not str(recommended).strip():
        raise ValueError("advisory missing recommended_model")
    confidence = payload.get("confidence_score", payload.get("confidenceScore", 0.0))
    basis = payload.get("comparison_basis", payload.get("comparisonBasis")) or [
        "durable-store"
    ]
    if isinstance(basis, str):
        basis = [basis]
    sample = payload.get("sample_count", payload.get("sampleCount", 0))
    freshness = payload.get("data_freshness_ts", payload.get("dataFreshnessTs")) or _utc_now_ts()
    return AdvisoryRecommendation(
        recommended_model=str(recommended),
        confidence_score=float(confidence),
        comparison_basis=[str(item) for item in basis],
        sample_count=int(sample),
        data_freshness_ts=str(freshness),
    )


def _advisory_store_path() -> Path | None:
    raw = os.environ.get(ADVISORY_STORE_ENV, "").strip()
    if not raw:
        return None
    root = Path(raw)
    candidate = root / ADVISORY_STORE_FILENAME
    if candidate.is_file():
        return candidate
    if root.is_file():
        return root
    return None


def hydrate_advisory_snapshot_from_store(
    task_type: str | None = None,
    *,
    force: bool = False,
) -> bool:
    """Load durable advisory observations and publish via replace_advisory_snapshot.

    Returns True when a snapshot was published. Staleness remains visible through
    ``data_freshness_ts`` on each recommendation (TR6).
    """
    global _HYDRATED_FROM_STORE
    path = _advisory_store_path()
    if path is None:
        return False
    with _SNAPSHOT_LOCK:
        if _HYDRATED_FROM_STORE and not force and _ADVISORY_SNAPSHOT:
            return True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False

    entries: dict[str, AdvisoryRecommendation] = {}
    try:
        if _looks_like_advisory(payload):
            key = str(task_type or "implement").strip() or "implement"
            entries[key] = _normalize_advisory(payload)
        else:
            for key, value in payload.items():
                if isinstance(value, Mapping) and _looks_like_advisory(value):
                    entries[str(key)] = _normalize_advisory(value)
    except (TypeError, ValueError):
        return False

    if not entries:
        return False
    replace_advisory_snapshot(entries)
    with _SNAPSHOT_LOCK:
        _HYDRATED_FROM_STORE = True
    return True


def get_current_advisory(
    task_type: str,
    dimension_record: dict[str, Any],
) -> AdvisoryRecommendation | None:
    """Return the current advisory recommendation or None (R15 / PRD 352 R22).

    Thread-safe via immutable snapshot cache. On miss, lazily hydrates from
    ``SW_ADVISORY_STORE`` so fresh processes observe durable data (R26).
    Returns ``None`` for all no-data paths (never raises for missing data).
    """
    del dimension_record  # reserved for future dimension-scoped lookup
    key = str(task_type or "").strip()
    if not key:
        return None
    with _SNAPSHOT_LOCK:
        snapshot = _ADVISORY_SNAPSHOT
    hit = snapshot.get(key)
    if hit is not None:
        return hit
    if hydrate_advisory_snapshot_from_store(key):
        with _SNAPSHOT_LOCK:
            snapshot = _ADVISORY_SNAPSHOT
        return snapshot.get(key)
    return None


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
