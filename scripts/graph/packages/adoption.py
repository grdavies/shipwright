#!/usr/bin/env python3
"""Producer/consumer adoption measures for workflow packages (PRD 272 R20)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

NAMED_PRODUCERS: tuple[str, ...] = (
    "shipwright",
    "shipwright-dogfood",
)

NAMED_CONSUMERS: tuple[str, ...] = (
    "shipwright",
    "shipwright-sibling-consumer",
)


@dataclass(frozen=True)
class AdoptionMetrics:
    reuse_count: int
    update_friction_seconds: float
    broken_pin_rate: float
    producers: tuple[str, ...]
    consumers: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "reuseCount": self.reuse_count,
            "updateFrictionSeconds": self.update_friction_seconds,
            "brokenPinRate": self.broken_pin_rate,
            "producers": list(self.producers),
            "consumers": list(self.consumers),
            "compatPolicy": {
                "deprecation": "semver-major",
                "revocation": "fail-closed",
                "upgrade": "digest-rebind-approval",
            },
        }


def report_adoption_metrics(
    counters: Mapping[str, int] | None = None,
) -> AdoptionMetrics:
    """Report rollout adoption measures for named producer/consumer paths (R20)."""
    stats = dict(counters or {})
    reuse = int(stats.get("reuseCount", 0))
    friction = float(stats.get("updateFrictionSeconds", 0.0))
    broken = float(stats.get("brokenPinAttempts", 0))
    attempts = float(stats.get("resolveAttempts", max(broken, 1.0)))
    return AdoptionMetrics(
        reuse_count=reuse,
        update_friction_seconds=friction,
        broken_pin_rate=broken / attempts if attempts else 0.0,
        producers=NAMED_PRODUCERS,
        consumers=NAMED_CONSUMERS,
    )
