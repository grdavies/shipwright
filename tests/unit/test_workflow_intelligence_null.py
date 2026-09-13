"""Null-preserving workflow intelligence ingestion — PRD 351 TS1, TS9."""
from __future__ import annotations

import pytest

import workflow_intelligence as wi


def test_missing_dimensions_stored_as_null_not_sentinels() -> None:
    """TS1 — missing task_type/effort_hint/complexity_indicators → null, not python/build/medium."""
    dimensions = wi.build_dimension_record({})
    assert dimensions["task_type"] is None
    assert dimensions["effort_hint"] is None
    assert dimensions["complexity_indicators"] is None
    for value in dimensions.values():
        assert value not in {"python", "build", "medium"}


def test_partial_dimensions_preserve_present_and_null_missing() -> None:
    dimensions = wi.build_dimension_record({"task_type": "implement", "effort_hint": ""})
    assert dimensions["task_type"] == "implement"
    assert dimensions["effort_hint"] is None
    assert dimensions["complexity_indicators"] is None


def test_comparison_group_excludes_null_dimension_records() -> None:
    """TS1 / R7 — comparison group filters out any null-dimension records."""
    records = [
        {
            "dimensions": {
                "task_type": "implement",
                "effort_hint": "medium",
                "complexity_indicators": "low",
            }
        },
        {
            "dimensions": {
                "task_type": None,
                "effort_hint": "medium",
                "complexity_indicators": "low",
            }
        },
        {
            "dimensions": {
                "task_type": "review",
                "effort_hint": "high",
                "complexity_indicators": "high",
            }
        },
        {"dimensions": wi.build_dimension_record({})},
    ]
    filtered = wi.filter_comparison_group(records)
    assert len(filtered) == 2
    assert all(wi.dimension_record_complete(r["dimensions"]) for r in filtered)


def test_cohort_ingest_dimensions_have_no_default_substitution() -> None:
    telemetry: dict = {}
    assert wi._cohort_dimension_value(telemetry, "language") is None
    assert wi._cohort_dimension_value(telemetry, "modelTier") is None
    assert wi._cohort_dimension_value(telemetry, "repoSize") is None


def test_advisory_requires_min_sample_count() -> None:
    with pytest.raises(wi.InsufficientSampleError, match="low-sample"):
        wi.build_advisory(
            recommended_model="claude-4",
            confidence_score=0.8,
            comparison_basis=["task_type"],
            sample_count=9,
            data_freshness_ts="2026-09-12T00:00:00Z",
        )


def test_advisory_metadata_shape_complete() -> None:
    advisory = wi.build_advisory(
        recommended_model="claude-4",
        confidence_score=0.8,
        comparison_basis=["task_type", "effort_hint"],
        sample_count=10,
        data_freshness_ts="2026-09-12T00:00:00Z",
    )
    assert set(advisory) == {
        "recommended_model",
        "confidence_score",
        "comparison_basis",
        "sample_count",
        "data_freshness_ts",
    }
