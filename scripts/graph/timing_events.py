#!/usr/bin/env python3
"""Append-only host-measured timing events for graph runs (PRD 271 R11/R11a/R28)."""
from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

# Host-measured categories (R11). Bookkeeping is recorded but excluded from attribution.
class TimingCategory(str, Enum):
    READY = "ready"
    QUEUE_WAIT = "queue-wait"
    RESOURCE_WAIT = "resource-wait"
    CONTENTION_WAIT = "contention-wait"
    EXECUTION = "execution"
    FANIN_WAIT = "fan-in-wait"
    BOOKKEEPING = "bookkeeping"


ATTRIBUTION_CATEGORIES = frozenset(
    {
        TimingCategory.READY,
        TimingCategory.QUEUE_WAIT,
        TimingCategory.RESOURCE_WAIT,
        TimingCategory.CONTENTION_WAIT,
        TimingCategory.EXECUTION,
        TimingCategory.FANIN_WAIT,
    }
)

_EXECUTION_CATEGORIES = frozenset({TimingCategory.EXECUTION})

_REQUIRED_EVENT_FIELDS = frozenset(
    {
        "seq",
        "nodeId",
        "category",
        "durationMs",
        "monotonicStartMs",
        "wallClockStartMs",
        "schedulerEpoch",
    }
)


class TimingEventError(ValueError):
    """Raised when timing event payloads are invalid."""


def wall_clock_ms() -> int:
    """Durable wall-clock anchor in milliseconds (R11)."""
    return int(time.time() * 1000)


def validate_timing_event(event: Mapping[str, Any]) -> dict[str, Any]:
    missing = sorted(_REQUIRED_EVENT_FIELDS - set(event))
    if missing:
        raise TimingEventError("timing event missing fields: " + ", ".join(missing))
    category = str(event["category"])
    if category not in {item.value for item in TimingCategory}:
        raise TimingEventError(f"unknown timing category: {category}")
    duration = int(event["durationMs"])
    if duration < 0:
        raise TimingEventError("durationMs cannot be negative")
    return {
        "seq": int(event["seq"]),
        "nodeId": str(event["nodeId"]),
        "category": category,
        "durationMs": duration,
        "monotonicStartMs": int(event["monotonicStartMs"]),
        "wallClockStartMs": int(event["wallClockStartMs"]),
        "schedulerEpoch": int(event["schedulerEpoch"]),
        **(
            {"detail": str(event["detail"])}
            if event.get("detail") is not None
            else {}
        ),
    }


@dataclass(frozen=True)
class NodeTimingAttribution:
    """Per-node measured wait/execution breakdown excluding bookkeeping (R11a/R28)."""

    node_id: str
    attributed_ms: int
    execution_ms: int
    waits_ms: int
    by_category: dict[str, int]
    bookkeeping_ms: int

    def as_payload(self) -> dict[str, Any]:
        return {
            "nodeId": self.node_id,
            "attributedMs": self.attributed_ms,
            "executionMs": self.execution_ms,
            "waitsMs": self.waits_ms,
            "byCategory": dict(sorted(self.by_category.items())),
            "bookkeepingMs": self.bookkeeping_ms,
        }


def aggregate_timing_events(
    events: Sequence[Mapping[str, Any]],
) -> dict[str, NodeTimingAttribution]:
    """Sum append-only intervals per node; bookkeeping excluded from attribution."""
    by_node: dict[str, dict[str, int]] = {}
    bookkeeping: dict[str, int] = {}
    for raw in events:
        event = validate_timing_event(raw)
        node_id = event["nodeId"]
        category = event["category"]
        duration = event["durationMs"]
        if category == TimingCategory.BOOKKEEPING.value:
            bookkeeping[node_id] = bookkeeping.get(node_id, 0) + duration
            continue
        if category not in {item.value for item in ATTRIBUTION_CATEGORIES}:
            continue
        bucket = by_node.setdefault(node_id, {})
        bucket[category] = bucket.get(category, 0) + duration

    result: dict[str, NodeTimingAttribution] = {}
    for node_id, categories in by_node.items():
        execution_ms = categories.get(TimingCategory.EXECUTION.value, 0)
        waits_ms = sum(
            value
            for key, value in categories.items()
            if key != TimingCategory.EXECUTION.value
        )
        attributed_ms = execution_ms + waits_ms
        result[node_id] = NodeTimingAttribution(
            node_id=node_id,
            attributed_ms=attributed_ms,
            execution_ms=execution_ms,
            waits_ms=waits_ms,
            by_category=categories,
            bookkeeping_ms=bookkeeping.get(node_id, 0),
        )
    return result


def observed_execution_overlap(events: Sequence[Mapping[str, Any]]) -> bool:
    """True when two execution intervals overlap in monotonic time (concurrency evidence)."""
    intervals: list[tuple[int, int]] = []
    for raw in events:
        event = validate_timing_event(raw)
        if event["category"] != TimingCategory.EXECUTION.value:
            continue
        start = event["monotonicStartMs"]
        end = start + event["durationMs"]
        intervals.append((start, end))
    intervals.sort()
    for index in range(1, len(intervals)):
        prev_end = intervals[index - 1][1]
        if intervals[index][0] < prev_end:
            return True
    return False


def causal_critical_path(
    node_ids: Sequence[str],
    predecessors: Mapping[str, Sequence[str]],
    attributions: Mapping[str, NodeTimingAttribution],
) -> dict[str, Any]:
    """Longest attributed path; parallel branches do not double-count sibling waits (R11a)."""
    order = list(node_ids)
    distances: dict[str, int] = {}
    previous: dict[str, str | None] = {}
    for node_id in order:
        weight = attributions.get(node_id)
        node_weight = weight.attributed_ms if weight is not None else 0
        preds = predecessors.get(node_id) or ()
        parent = max(preds, key=lambda item: distances.get(item, 0), default=None)
        parent_dist = distances[parent] if parent is not None else 0
        distances[node_id] = node_weight + parent_dist
        previous[node_id] = parent

    total = max(distances.values(), default=0)
    if total <= 0:
        return {
            "omitted": True,
            "reason": "zero-weight",
            "estimated": False,
            "measured": True,
            "durationMs": 0,
            "nodes": [],
        }

    end = max(order, key=lambda item: distances[item])
    path: list[str] = []
    cursor: str | None = end
    while cursor is not None:
        path.append(cursor)
        cursor = previous.get(cursor)
    path.reverse()

    return {
        "omitted": False,
        "estimated": False,
        "measured": True,
        "provenance": ["timing-events"],
        "durationMs": distances[end],
        "nodes": [
            {
                "nodeId": node_id,
                "cumulativeDurationMs": distances[node_id],
                "durationMs": attributions[node_id].attributed_ms
                if node_id in attributions
                else 0,
                "provenance": "timing-events",
                "attribution": attributions[node_id].as_payload()
                if node_id in attributions
                else None,
            }
            for node_id in path
        ],
    }


class TimingEventRecorder:
    """Append-only recorder for the scheduler owning loop (R11/R17)."""

    def __init__(
        self,
        journal: Any,
        *,
        clock: Any,
        run_started_monotonic: float,
        scheduler_epoch: int = 0,
    ) -> None:
        self._journal = journal
        self._clock = clock
        self._run_start = run_started_monotonic
        self._epoch = scheduler_epoch
        self._seq = 0
        self._events: list[dict[str, Any]] = []

    @property
    def events(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._events)

    def _monotonic_ms(self) -> int:
        return int((self._clock() - self._run_start) * 1000)

    def record_interval(
        self,
        node_id: str,
        category: TimingCategory,
        *,
        duration_ms: int,
        monotonic_start_ms: int | None = None,
        detail: str | None = None,
    ) -> dict[str, Any]:
        if duration_ms < 0:
            raise TimingEventError("durationMs cannot be negative")
        start_ms = (
            monotonic_start_ms if monotonic_start_ms is not None else self._monotonic_ms()
        )
        self._seq += 1
        payload: dict[str, Any] = {
            "seq": self._seq,
            "nodeId": node_id,
            "category": category.value,
            "durationMs": int(duration_ms),
            "monotonicStartMs": int(start_ms),
            "wallClockStartMs": wall_clock_ms(),
            "schedulerEpoch": self._epoch,
        }
        if detail:
            payload["detail"] = detail
        validated = validate_timing_event(payload)
        self._journal.append_timing_event(validated)
        self._events.append(validated)
        return validated

    def record_bookkeeping(self, duration_ms: int, *, detail: str = "journal") -> None:
        if duration_ms <= 0:
            return
        self.record_interval(
            "__bookkeeping__",
            TimingCategory.BOOKKEEPING,
            duration_ms=duration_ms,
            detail=detail,
        )


__all__ = [
    "ATTRIBUTION_CATEGORIES",
    "NodeTimingAttribution",
    "TimingCategory",
    "TimingEventError",
    "TimingEventRecorder",
    "aggregate_timing_events",
    "causal_critical_path",
    "observed_execution_overlap",
    "validate_timing_event",
    "wall_clock_ms",
]
