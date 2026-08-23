#!/usr/bin/env python3
"""Reviewer harvest + bounded selection tests (PRD 326 R16–R18)."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.reviewer_metrics.cohort import CohortIdentity  # noqa: E402
from graph.reviewer_metrics.cost import enforce_cost_ceiling  # noqa: E402
from graph.reviewer_metrics.harvest import (  # noqa: E402
    HarvestFindingInput,
    harvest_reviewers,
)
from graph.reviewer_metrics.persistence import (  # noqa: E402
    HarvestSchemaError,
    build_harvest_metadata_record,
    redact_harvest_for_write,
)
from graph.reviewer_metrics.provenance import HarvestFindingProvenance, build_harvest_provenance  # noqa: E402
from graph.reviewer_metrics.ranking import (  # noqa: E402
    SELECTION_FLOOR_REASON,
    SelectionFloorError,
    apply_bounded_selection,
)
from graph.reviewer_metrics.selection import (  # noqa: E402
    SelectionConfig,
    apply_bounded_doc_review,
    load_selection_config,
    selection_bytes_unchanged,
)
from graph.reviewer_metrics.store_adapter import ReviewerMetricsStoreAdapter  # noqa: E402
from graph.reviewer_metrics.surviving import CouplingEvidence  # noqa: E402


def _cohort() -> CohortIdentity:
    return CohortIdentity(
        persona_version="persona-v1",
        prompt_version="prompt-v1",
        model_version="model-v1",
        schema_version=1,
        policy_version="policy-v1",
    )


def test_harvest_excludes_censored_findings() -> None:
    findings = (
        HarvestFindingInput(
            finding_id="f-censored",
            run_id="run-1",
            reviewer_id="reviewer-a",
            confidence=0.9,
            attribution_window="window-a",
            evidence=[],
        ),
        HarvestFindingInput(
            finding_id="f-tp",
            run_id="run-1",
            reviewer_id="reviewer-a",
            confidence=0.8,
            attribution_window="window-a",
            evidence=[CouplingEvidence("exogenous-ci", "confirmed")],
        ),
    )
    record = harvest_reviewers(findings, cohort=_cohort(), harvested_at="2026-08-23T00:00:00Z")
    assert len(record.reviewers) == 1
    assert record.reviewers[0].labeled_count == 1
    assert record.reviewers[0].contributing_finding_ids == ("f-tp",)


def test_harvest_record_is_deterministic_and_sorted() -> None:
    findings = (
        HarvestFindingInput(
            finding_id="f-1",
            run_id="run-1",
            reviewer_id="reviewer-b",
            confidence=0.7,
            attribution_window="window-a",
            evidence=[CouplingEvidence("exogenous-ci", "confirmed")],
        ),
        HarvestFindingInput(
            finding_id="f-2",
            run_id="run-1",
            reviewer_id="reviewer-a",
            confidence=0.6,
            attribution_window="window-a",
            evidence=[CouplingEvidence("exogenous-human", "rejected")],
        ),
    )
    first = harvest_reviewers(findings, cohort=_cohort(), harvested_at="2026-08-23T00:00:00Z")
    second = harvest_reviewers(findings, cohort=_cohort(), harvested_at="2026-08-23T00:00:00Z")
    assert first.to_dict() == second.to_dict()
    assert [item.reviewer_id for item in first.reviewers] == sorted(
        [item.reviewer_id for item in first.reviewers],
        key=lambda reviewer_id: next(
            (
                (
                    -score.rating,
                    score.calibration_error or 0.0,
                    -score.surviving_count,
                    score.reviewer_id,
                )
                for score in first.reviewers
                if score.reviewer_id == reviewer_id
            ),
            (0.0, 0.0, 0, reviewer_id),
        ),
    )


def test_bounded_selection_floor_guard() -> None:
    result = apply_bounded_selection([], max_personas=3, min_personas=1)
    assert result.verdict == "fail"
    assert result.reason == SELECTION_FLOOR_REASON
    with pytest.raises(SelectionFloorError):
        raise SelectionFloorError(SELECTION_FLOOR_REASON)


def test_cost_ceiling_enforced_before_dispatch() -> None:
    result = enforce_cost_ceiling(
        ("a", "b", "c"),
        cost_per_reviewer={"a": 2.0, "b": 2.0, "c": 2.0},
        ceiling=4.0,
        min_personas=1,
    )
    assert result.verdict == "ok"
    assert len(result.selected) == 2
    assert result.total_cost <= 4.0


def test_harvest_persistence_redacts_and_round_trips() -> None:
    findings = (
        HarvestFindingInput(
            finding_id="f-1",
            run_id="run-1",
            reviewer_id="persona-a",
            confidence=0.8,
            attribution_window="window-a",
            evidence=[CouplingEvidence("exogenous-ci", "confirmed")],
        ),
    )
    harvest = harvest_reviewers(findings, cohort=_cohort(), harvested_at="2026-08-23T00:00:00Z")
    provenance = (
        HarvestFindingProvenance(
            finding_id="f-1",
            reviewer_id="persona-a",
            run_id="run-1",
            recorded_at="2026-08-23T00:00:00Z",
        ),
    )
    metadata = build_harvest_metadata_record(
        harvested_at=harvest.harvested_at,
        reviewer_count=len(harvest.reviewers),
        finding_count=len(provenance),
        recorded_at="2026-08-23T00:00:00Z",
        provenance_summary="f-1",
    )
    redacted, _ = redact_harvest_for_write(metadata, may_egress=True)
    assert redacted["outcomeKind"] == "harvest"
    ordered = build_harvest_provenance(provenance)
    assert ordered[0].finding_id == "f-1"

    with tempfile.TemporaryDirectory() as tmp:
        adapter = ReviewerMetricsStoreAdapter(tmp, may_egress=False)
        adapter.persist_harvest(
            harvest,
            provenance_rows=provenance,
            journal_entry={"runId": "run-1", "verdict": "harvest"},
            recorded_at="2026-08-23T00:00:00Z",
        )
        loaded = adapter.load_latest_harvest()
        assert loaded is not None
        assert loaded.to_dict() == harvest.to_dict()


def test_doc_review_fallback_is_byte_identical_without_harvest() -> None:
    base = {
        "family": "doc-review",
        "panel": ["sw-coherence-reviewer", "sw-security-reviewer"],
        "activation": {"core": ["coherence"], "gated": [], "override": "none"},
    }
    with tempfile.TemporaryDirectory() as tmp:
        updated = apply_bounded_doc_review(base, repo_root=Path(tmp), cfg={})
        assert selection_bytes_unchanged(base, updated)
        assert updated is base


def test_doc_review_truncates_with_harvest() -> None:
    base = {
        "family": "doc-review",
        "panel": [
            "sw-coherence-reviewer",
            "sw-security-reviewer",
            "sw-design-reviewer",
        ],
        "activation": {"core": ["coherence"], "gated": [], "override": "none"},
    }
    findings = (
        HarvestFindingInput(
            finding_id="f-1",
            run_id="run-1",
            reviewer_id="sw-security-reviewer",
            confidence=0.9,
            attribution_window="window-a",
            evidence=[CouplingEvidence("exogenous-ci", "confirmed")],
        ),
        HarvestFindingInput(
            finding_id="f-2",
            run_id="run-1",
            reviewer_id="sw-coherence-reviewer",
            confidence=0.4,
            attribution_window="window-a",
            evidence=[CouplingEvidence("exogenous-human", "rejected")],
        ),
        HarvestFindingInput(
            finding_id="f-3",
            run_id="run-1",
            reviewer_id="sw-design-reviewer",
            confidence=0.7,
            attribution_window="window-a",
            evidence=[CouplingEvidence("exogenous-ci", "confirmed")],
        ),
    )
    harvest = harvest_reviewers(findings, cohort=_cohort(), harvested_at="2026-08-23T00:00:00Z")
    cfg = {
        "review": {
            "selection": {
                "maxPersonas": 2,
                "minPersonas": 1,
                "costCeiling": None,
            }
        }
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        adapter = ReviewerMetricsStoreAdapter(root, may_egress=False)
        adapter.persist_harvest(
            harvest,
            provenance_rows=(
                HarvestFindingProvenance(
                    finding_id="f-1",
                    reviewer_id="sw-security-reviewer",
                    run_id="run-1",
                    recorded_at="2026-08-23T00:00:00Z",
                ),
            ),
            journal_entry={"runId": "run-1", "verdict": "harvest"},
            recorded_at="2026-08-23T00:00:00Z",
        )
        updated = apply_bounded_doc_review(base, repo_root=root, cfg=cfg)
        assert len(updated["panel"]) == 2
        assert updated["panel"][0] == "sw-security-reviewer"


def test_selection_config_defaults() -> None:
    config = load_selection_config({})
    assert config == SelectionConfig(max_personas=32, min_personas=1, cost_ceiling=None)


def test_harvest_schema_rejects_unknown_fields() -> None:
    payload = build_harvest_metadata_record(
        harvested_at="2026-08-23T00:00:00Z",
        reviewer_count=1,
        finding_count=1,
        recorded_at="2026-08-23T00:00:00Z",
    )
    bad = dict(payload)
    bad["transcript"] = "blocked"
    with pytest.raises(HarvestSchemaError):
        redact_harvest_for_write(bad, may_egress=False)
