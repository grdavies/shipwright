#!/usr/bin/env python3
"""Deterministic metrics for pipeline and barrier graph scheduling."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

SERIAL_EQUIVALENT_MAX_CONCURRENCY = 1

ALLOWED_EXTERNAL_AUTHORIZERS = frozenset(
    {
        "cutover-full-ownership-gate",
        "graph-runtime-cutover",
    }
)


class SchedulingMode(str, Enum):
    PIPELINE = "pipeline"
    BARRIER = "barrier"


@dataclass(frozen=True)
class ScheduledItem:
    item_id: str
    start_ms: int
    end_ms: int
    slots: int = 1
    mode: SchedulingMode = SchedulingMode.PIPELINE

    def __post_init__(self) -> None:
        if self.start_ms < 0 or self.end_ms < self.start_ms:
            raise ValueError("scheduled item has an invalid time range")
        if self.slots < 1:
            raise ValueError("scheduled item slots must be positive")

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True)
class SchedulingMetrics:
    serial_baseline_ms: int
    elapsed_ms: int
    speedup: float
    barrier_idle_ms: int
    slot_utilization: float

    def as_dict(self) -> dict[str, int | float]:
        return {
            "serialBaselineMs": self.serial_baseline_ms,
            "elapsedMs": self.elapsed_ms,
            "speedup": self.speedup,
            "barrierIdleMs": self.barrier_idle_ms,
            "slotUtilization": self.slot_utilization,
        }


@dataclass(frozen=True)
class RegressionBudget:
    """Promotion regression ceilings for post-cutover dogfood evidence (R4)."""

    wall_clock_ms: int
    cache_hit_rate_min: float
    max_cost: float
    max_failures: int
    max_retries: int
    scheduler_overhead_ms: int


@dataclass(frozen=True)
class PromotionMetrics:
    """Measured baselines recorded during cutover promotion (R4)."""

    wall_clock_ms: int
    cache_hit_rate: float
    total_cost: float
    failure_count: int
    retry_count: int
    scheduler_overhead_ms: int

    def within_budget(self, budget: RegressionBudget) -> bool:
        return (
            self.wall_clock_ms <= budget.wall_clock_ms
            and self.cache_hit_rate >= budget.cache_hit_rate_min
            and self.total_cost <= budget.max_cost
            and self.failure_count <= budget.max_failures
            and self.retry_count <= budget.max_retries
            and self.scheduler_overhead_ms <= budget.scheduler_overhead_ms
        )

    def as_dict(self) -> dict[str, int | float]:
        return {
            "wallClockMs": self.wall_clock_ms,
            "cacheHitRate": self.cache_hit_rate,
            "totalCost": self.total_cost,
            "failureCount": self.failure_count,
            "retryCount": self.retry_count,
            "schedulerOverheadMs": self.scheduler_overhead_ms,
        }


@dataclass(frozen=True)
class MitigationLane:
    """Serial-equivalent mitigation lane without the legacy serial adapter (R4)."""

    max_concurrency: int = SERIAL_EQUIVALENT_MAX_CONCURRENCY
    cache_enabled: bool = True

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("mitigation lane max_concurrency must be positive")
        if not is_serial_equivalent(self.max_concurrency):
            raise ValueError(
                "mitigation lane requires serial-equivalent maxConcurrency=1"
            )


@dataclass(frozen=True)
class ExternalDispatchAuthorization:
    """Named authorizer plus durable evidence for leaving internal_only (R4)."""

    authorizer: str
    evidence_ref: str


def is_serial_equivalent(max_concurrency: int) -> bool:
    return max_concurrency == SERIAL_EQUIVALENT_MAX_CONCURRENCY


def authorize_external_dispatch(
    authorization: ExternalDispatchAuthorization | None,
) -> ExternalDispatchAuthorization:
    """Fail closed when production dispatch is requested without cutover evidence."""
    if authorization is None:
        raise PermissionError(
            "leaving internal_only requires a named authorizer and recorded evidence"
        )
    authorizer = authorization.authorizer.strip()
    evidence_ref = authorization.evidence_ref.strip()
    if not authorizer or not evidence_ref:
        raise PermissionError(
            "leaving internal_only requires a named authorizer and recorded evidence"
        )
    if authorizer not in ALLOWED_EXTERNAL_AUTHORIZERS:
        raise PermissionError(f"unrecognized cutover authorizer: {authorizer}")
    return ExternalDispatchAuthorization(authorizer=authorizer, evidence_ref=evidence_ref)


def measure_schedule(
    items: Iterable[ScheduledItem],
    *,
    available_slots: int,
) -> SchedulingMetrics:
    """Report comparable serial, pipeline, barrier-idle, and utilization metrics."""
    scheduled = tuple(items)
    if available_slots < 1:
        raise ValueError("available_slots must be positive")
    if not scheduled:
        return SchedulingMetrics(0, 0, 1.0, 0, 0.0)

    origin = min(item.start_ms for item in scheduled)
    finish = max(item.end_ms for item in scheduled)
    elapsed = finish - origin
    serial = sum(item.duration_ms for item in scheduled)
    busy_slot_ms = sum(item.duration_ms * item.slots for item in scheduled)
    if any(item.slots > available_slots for item in scheduled):
        raise ValueError("scheduled item exceeds available slots")

    barrier_idle = 0
    for barrier in (item for item in scheduled if item.mode is SchedulingMode.BARRIER):
        active = sum(
            min(candidate.end_ms, barrier.end_ms)
            - max(candidate.start_ms, barrier.start_ms)
            for candidate in scheduled
            if candidate.item_id != barrier.item_id
            and candidate.end_ms > barrier.start_ms
            and candidate.start_ms < barrier.end_ms
        )
        barrier_idle += max(0, barrier.duration_ms * available_slots - active)

    capacity = elapsed * available_slots
    return SchedulingMetrics(
        serial_baseline_ms=serial,
        elapsed_ms=elapsed,
        speedup=(serial / elapsed) if elapsed else 1.0,
        barrier_idle_ms=barrier_idle,
        slot_utilization=(busy_slot_ms / capacity) if capacity else 0.0,
    )


def serial_equivalent_metrics(
    items: Iterable[ScheduledItem],
) -> SchedulingMetrics:
    """Measure a schedule under the serial-equivalent maxConcurrency=1 lane."""
    return measure_schedule(items, available_slots=SERIAL_EQUIVALENT_MAX_CONCURRENCY)


def validate_scheduling_mode(node_kind: str, mode: str | SchedulingMode) -> SchedulingMode:
    """Reject a barrier node accidentally declared as independent pipeline work."""
    parsed = SchedulingMode(mode)
    if node_kind == "barrier" and parsed is not SchedulingMode.BARRIER:
        raise ValueError("barrier nodes must use barrier scheduling mode")
    return parsed
