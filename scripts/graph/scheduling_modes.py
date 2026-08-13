#!/usr/bin/env python3
"""Deterministic metrics for pipeline and barrier graph scheduling."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


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


def validate_scheduling_mode(node_kind: str, mode: str | SchedulingMode) -> SchedulingMode:
    """Reject a barrier node accidentally declared as independent pipeline work."""
    parsed = SchedulingMode(mode)
    if node_kind == "barrier" and parsed is not SchedulingMode.BARRIER:
        raise ValueError("barrier nodes must use barrier scheduling mode")
    return parsed
