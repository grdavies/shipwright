#!/usr/bin/env python3
"""Receipt-backed node cost telemetry and bounded model escalation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from model_policy_lib import (
    ESCALATION_TRIGGERS,
    ModelPolicy,
    next_model_tier as policy_next_model_tier,
    ordered_tiers,
)

# Public tier order is config-derived via ModelPolicy, not a fixed private tuple.
TIER_ORDER = ordered_tiers({})


@dataclass(frozen=True)
class NodeCostTelemetry:
    node_id: str
    tokens: int
    latency_ms: int
    attempts: int
    accepted: bool
    verification_survived: bool
    cost: float

    @property
    def retries(self) -> int:
        return max(0, self.attempts - 1)

    @property
    def cost_per_accepted_result(self) -> float | None:
        return self.cost if self.accepted and self.verification_survived else None

    def as_receipt_fields(self) -> dict[str, Any]:
        return {
            "tokens": self.tokens,
            "durationMs": self.latency_ms,
            "attempts": self.attempts,
            "successRetry": {"accepted": self.accepted, "retries": self.retries},
            "verificationSurvival": self.verification_survived,
            "costPerAcceptedResult": self.cost_per_accepted_result,
        }


def telemetry_from_receipt(
    receipt: Mapping[str, Any],
    *,
    token_cost: float = 0.0,
) -> NodeCostTelemetry:
    tokens = int(receipt.get("tokens", 0))
    attempts = int(receipt.get("attempts", 1))
    accepted = receipt.get("verdict") == "pass"
    coverage = receipt.get("coverage") or {}
    survived = bool(coverage.get("verificationSurvived", accepted))
    return NodeCostTelemetry(
        node_id=str(receipt.get("nodeId", "")),
        tokens=tokens,
        latency_ms=int(receipt.get("durationMs", 0)),
        attempts=attempts,
        accepted=accepted,
        verification_survived=survived,
        cost=tokens * token_cost,
    )


def observability_fields(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Project receipt telemetry onto the stable read-only command surface."""
    telemetry = telemetry_from_receipt(receipt)
    return {
        "tokens": telemetry.tokens,
        "latencyMs": telemetry.latency_ms,
        "attempts": telemetry.attempts,
        "retries": telemetry.retries,
        "verificationSurvived": telemetry.verification_survived,
        "costPerAcceptedResult": telemetry.cost_per_accepted_result,
    }


def next_model_tier(
    current_tier: str,
    triggers: Iterable[str],
    *,
    allowed_tiers: Iterable[str],
    tiers: Mapping[str, str] | None = None,
) -> str:
    """Escalate via shared ModelPolicy; ``tiers`` is ``models.tiers`` from workflow config."""
    return policy_next_model_tier(
        current_tier,
        triggers,
        allowed_tiers=allowed_tiers,
        tiers=tiers,
    )


__all__ = [
    "ESCALATION_TRIGGERS",
    "ModelPolicy",
    "NodeCostTelemetry",
    "TIER_ORDER",
    "next_model_tier",
    "observability_fields",
    "telemetry_from_receipt",
]
