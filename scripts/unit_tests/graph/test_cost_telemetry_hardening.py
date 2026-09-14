"""Cost telemetry hardening — PRD 351 TS5 (R21–R23)."""
from __future__ import annotations

from graph.cost_telemetry import (
    aggregate,
    ingest_record,
    reset_attribution_accumulators,
    suspect_count,
    unverified_exclusion_count,
)


def setup_function() -> None:
    reset_attribution_accumulators()


def test_unattested_zero_tokens_marked_suspect() -> None:
    """TS5 / R21 — unattested zero tokens → telemetry_suspect, excluded from cost."""
    record = {
        "tokens_input": 0,
        "tokens_output": 100,
        "zero_tokens_attested": False,
        "cost": 5.0,
        "verification_result": "pass",
        "rework_required": False,
    }
    ingest_record(record)
    assert record["telemetry_suspect"] is True
    assert suspect_count() == 1
    result = aggregate(split_verified=False)
    assert result["cost_per_task_all_count"] == 0


def test_attested_zero_tokens_not_suspect() -> None:
    record = {
        "tokens_input": 0,
        "tokens_output": 0,
        "zero_tokens_attested": True,
        "cost": 0.0,
        "verification_result": "pass",
        "rework_required": False,
    }
    ingest_record(record)
    assert record.get("telemetry_suspect") is not True
    assert suspect_count() == 0
    result = aggregate(split_verified=False)
    assert result["cost_per_task_all_count"] == 1


def test_unknown_verification_excluded_from_verified_cost() -> None:
    """TS5 / R22 — unknown verification excluded; unverified_exclusion_count increments."""
    ingest_record(
        {
            "tokens_input": 10,
            "tokens_output": 10,
            "cost": 2.0,
            "verification_result": "unknown",
            "rework_required": False,
        }
    )
    ingest_record(
        {
            "tokens_input": 10,
            "tokens_output": 10,
            "cost": 4.0,
            "verification_result": "pass",
            "rework_required": False,
        }
    )
    result = aggregate(split_verified=True)
    assert result["cost_per_task_all_count"] == 2
    assert result["cost_per_verified_successful_task_count"] == 1
    assert result["cost_per_verified_successful_task"] == 4.0
    assert unverified_exclusion_count() == 1


def test_split_verified_aggregate_shape() -> None:
    """TS5 / R23 — split aggregate emits both all and verified metrics."""
    ingest_record(
        {
            "tokens_input": 5,
            "tokens_output": 5,
            "cost": 3.0,
            "verification_result": "pass",
            "rework_required": False,
        }
    )
    plain = aggregate(split_verified=False)
    assert "cost_per_task_all" in plain and "cost_per_task_all_count" in plain
    assert "cost_per_task_all_confidence" in plain
    assert "cost_failed_attempts" in plain
    split = aggregate(split_verified=True)
    assert "cost_per_verified_successful_task" in split
    assert "cost_per_verified_successful_task_count" in split


def test_never_infer_verification_from_acceptance() -> None:
    """R22 — acceptance does not set verification_result."""
    record = {
        "tokens_input": 1,
        "tokens_output": 1,
        "cost": 1.0,
        "accepted": True,
        "verification_result": "unknown",
        "rework_required": False,
    }
    ingest_record(record)
    assert record["verification_result"] == "unknown"
    result = aggregate(split_verified=True)
    assert result["cost_per_verified_successful_task_count"] == 0


def test_unknown_cost_not_coerced_to_zero() -> None:
    """PRD 352 R24 — unknown costs stay None; confidence marker emitted."""
    ingest_record(
        {
            "tokens_input": None,
            "tokens_output": None,
            "verification_result": "pass",
            "rework_required": False,
        }
    )
    result = aggregate(split_verified=False)
    assert result["cost_per_task_all"] is None
    assert result["cost_per_task_all_confidence"] == "unknown"
    assert result["cost_per_task_all"] != 0.0


def test_failed_attempt_count_emits_bucket() -> None:
    """PRD 352 R25 — failed_attempt_count contributes cost_failed_attempts bucket."""
    ingest_record(
        {
            "tokens_input": 10,
            "tokens_output": 10,
            "cost": 8.0,
            "attempt_count": 2,
            "failed_attempt_count": 1,
            "zero_tokens_attested": True,
            "verification_result": "pass",
            "rework_required": False,
        }
    )
    result = aggregate(split_verified=False)
    assert result["cost_failed_attempts"] == 4.0
    assert result["cost_failed_attempts_confidence"] == "estimated"

