#!/usr/bin/env python3
"""Receipt-backed node cost telemetry, attribution ingest, and bounded model escalation."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, MutableMapping

from model_policy_lib import (
    ESCALATION_TRIGGERS,
    ModelPolicy,
    next_model_tier as policy_next_model_tier,
    ordered_tiers,
)

# Public tier order is config-derived via ModelPolicy, not a fixed private tuple.
TIER_ORDER = ordered_tiers({})

# Attribution ingest accumulators (R21, R22).
_suspect_count = 0
_unverified_exclusion_count = 0
_ingested_records: list[dict[str, Any]] = []


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


def reset_attribution_accumulators() -> None:
    """Test helper — clear ingest accumulators and in-memory records."""
    global _suspect_count, _unverified_exclusion_count, _ingested_records
    _suspect_count = 0
    _unverified_exclusion_count = 0
    _ingested_records = []


def suspect_count() -> int:
    return _suspect_count


def unverified_exclusion_count() -> int:
    return _unverified_exclusion_count


def _token_value(record: Mapping[str, Any], key: str) -> int | None:
    raw = record.get(key)
    if raw is None:
        return None
    return int(raw)


def ingest_record(record: MutableMapping[str, Any]) -> None:
    """Ingest an attribution record into cost telemetry (R21, R22).

    Unattested zero tokens mark the record ``telemetry_suspect`` and exclude it
    from cost calculations. Verification is never inferred from acceptance.
    # NEVER infer verification_result from acceptance — R22
    """
    global _suspect_count, _ingested_records

    tokens_input = _token_value(record, "tokens_input")
    tokens_output = _token_value(record, "tokens_output")
    zero_present = tokens_input == 0 or tokens_output == 0
    attested = record.get("zero_tokens_attested") is True

    if zero_present and not attested:
        record["telemetry_suspect"] = True
        _suspect_count += 1
        _ingested_records.append(dict(record))
        return

    # # NEVER infer verification_result from acceptance — R22
    # Leave verification_result untouched; unknown stays unknown.
    _ingested_records.append(dict(record))


def _record_cost(record: Mapping[str, Any]) -> float:
    tokens_input = _token_value(record, "tokens_input") or 0
    tokens_output = _token_value(record, "tokens_output") or 0
    explicit = record.get("cost")
    if explicit is not None:
        return float(explicit)
    return float(tokens_input + tokens_output)


def aggregate(split_verified: bool = False) -> dict[str, Any]:
    """Aggregate cost metrics over ingested attribution records (R23).

    When ``split_verified`` is True, also emit cost-per-verified-successful-task
    using only ``verification_result == "pass"`` and ``rework_required is False``.
    Records with ``verification_result == "unknown"`` are excluded from the
    verified metric and counted in ``_unverified_exclusion_count``.
    # NEVER infer verification_result from acceptance — R22
    """
    global _unverified_exclusion_count

    eligible = [r for r in _ingested_records if not r.get("telemetry_suspect")]
    all_count = len(eligible)
    all_cost = sum(_record_cost(r) for r in eligible)
    cost_per_task_all = (all_cost / all_count) if all_count else 0.0

    result: dict[str, Any] = {
        "cost_per_task_all": cost_per_task_all,
        "cost_per_task_all_count": all_count,
    }

    if not split_verified:
        return result

    verified: list[dict[str, Any]] = []
    for record in eligible:
        verification = record.get("verification_result")
        # # NEVER infer verification_result from acceptance — R22
        if verification == "unknown" or verification is None:
            _unverified_exclusion_count += 1
            continue
        if verification == "pass" and record.get("rework_required") is False:
            verified.append(record)

    verified_count = len(verified)
    if verified_count:
        verified_cost = sum(_record_cost(r) for r in verified)
        cost_per_verified: float | None = verified_cost / verified_count
    else:
        cost_per_verified = None

    result["cost_per_verified_successful_task"] = cost_per_verified
    result["cost_per_verified_successful_task_count"] = verified_count
    return result


def health_snapshot() -> dict[str, Any]:
    """Lightweight telemetry-health counters without full aggregate recalculation."""
    eligible = [r for r in _ingested_records if not r.get("telemetry_suspect")]
    return {
        "total_records": len(_ingested_records),
        "suspect_count": _suspect_count,
        "unverified_exclusion_count": _unverified_exclusion_count,
        "cost_per_task_all_count": len(eligible),
        "cost_per_verified_successful_task_count": sum(
            1
            for r in eligible
            if r.get("verification_result") == "pass" and r.get("rework_required") is False
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cost telemetry aggregation (PRD 351)")
    sub = parser.add_subparsers(dest="command", required=True)
    agg = sub.add_parser("aggregate", help="Emit cost aggregate JSON")
    agg.add_argument(
        "--split-verified",
        action="store_true",
        help="Also emit cost_per_verified_successful_task metrics (R23)",
    )
    args = parser.parse_args(argv)
    if args.command == "aggregate":
        print(json.dumps(aggregate(split_verified=bool(args.split_verified)), indent=2))
        return 0
    return 2


__all__ = [
    "ESCALATION_TRIGGERS",
    "ModelPolicy",
    "NodeCostTelemetry",
    "TIER_ORDER",
    "aggregate",
    "health_snapshot",
    "ingest_record",
    "next_model_tier",
    "observability_fields",
    "reset_attribution_accumulators",
    "suspect_count",
    "telemetry_from_receipt",
    "unverified_exclusion_count",
]


if __name__ == "__main__":
    sys.exit(main())
