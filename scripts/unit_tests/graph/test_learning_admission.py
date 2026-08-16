#!/usr/bin/env python3
"""PRD 272 phase-4 learning store admission and exogenous routing tests."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.learning_consumers import (  # noqa: E402
    aggregate_cohort_stats,
    recommend_tier_from_cohort,
    routing_cohort_stats,
)
from graph.learning_store import (  # noqa: E402
    AUTHORIZED_WRITER,
    LearningEvent,
    LearningStore,
    ProvenanceRejected,
    derive_event_from_receipt,
    journal_digest,
    validate_admission,
)
from model_policy_lib import ModelPolicy, recommend_implement_tier  # noqa: E402


def _journal(run_id: str = "run-1") -> dict:
    return {"runId": run_id, "verdict": "merge-ready-green", "language": "python"}


def test_learning_event_schema_and_named_writer() -> None:
    digest = journal_digest(_journal())
    event = LearningEvent(
        schema_version=1,
        event_id="evt-1",
        run_id="run-1",
        provenance="live",
        journal_digest=digest,
        cohort_dimensions={"workflowType": "ship"},
        outcomes={"readyWithoutRework": True},
        recorded_at="2026-08-16T00:00:00Z",
    )
    payload = event.to_dict()
    assert payload["writer"] == AUTHORIZED_WRITER
    roundtrip = LearningEvent.from_dict(payload)
    assert roundtrip.run_id == "run-1"


def test_rejects_bad_provenance_on_read() -> None:
    digest = journal_digest(_journal())
    with pytest.raises(ProvenanceRejected):
        LearningEvent.from_dict(
            {
                "schemaVersion": 1,
                "eventId": "evt-1",
                "runId": "run-1",
                "provenance": "synthetic",
                "journalDigest": digest,
                "cohortDimensions": {},
                "outcomes": {},
                "recordedAt": "2026-08-16T00:00:00Z",
                "writer": AUTHORIZED_WRITER,
                "terminallySettled": True,
                "kernelCompiled": True,
            }
        )


def test_shadow_benchmark_excluded_from_routing_cohort() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = LearningStore(tmp)
        journal = _journal("live-run")
        store.append_from_journal(
            journal,
            provenance="live",
            cohort_dimensions={"workflowType": "ship"},
            outcomes={"readyWithoutRework": True},
            for_routing_cohort=True,
        )
        store.append_from_journal(
            _journal("shadow-run"),
            provenance="shadow",
            cohort_dimensions={"workflowType": "ship"},
            outcomes={"readyWithoutRework": True},
        )
        routing = store.query_routing_cohort()
        assert len(routing) == 1
        assert routing[0].provenance == "live"
        with pytest.raises(ProvenanceRejected):
            validate_admission(
                provenance="benchmark",
                terminally_settled=True,
                kernel_compiled=True,
                for_routing_cohort=True,
            )


def test_export_before_gc_and_derivation_redaction() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = LearningStore(tmp, may_egress=True)
        store.append_from_journal(
            _journal(),
            provenance="live",
            cohort_dimensions={"riskClass": "standard"},
            outcomes={"readyWithoutRework": True},
        )
        export_path = Path(tmp) / "export.json"
        store.export_before_gc(export_path)
        snapshot = json.loads(export_path.read_text(encoding="utf-8"))
        assert len(snapshot["events"]) == 1
        derived = derive_event_from_receipt(_journal("run-2"), provenance="replay", may_egress=True)
        assert derived["appliedRedaction"]["destination"] == "external"


def test_exogenous_gate_blocks_tier_downgrade_without_signal() -> None:
    policy = ModelPolicy.from_tiers(
        {"cheap": "cheap-model", "build": "build-model", "mid": "mid-model", "deep": "deep-model"}
    )
    stats = aggregate_cohort_stats(
        (
            LearningEvent(
                schema_version=1,
                event_id="evt-1",
                run_id="run-1",
                provenance="live",
                journal_digest=journal_digest(_journal()),
                cohort_dimensions={},
                outcomes={"readyWithoutRework": True},
                recorded_at="2026-08-16T00:00:00Z",
            ),
        ),
        hold_detection_config="detector-v1",
    )
    recommendation = recommend_tier_from_cohort(
        current_tier="build",
        stats=stats,
        baseline_exogenous={"postMergeRevertRate": 0.01},
        policy=policy,
        allowed_tiers=("cheap", "build", "mid", "deep"),
        proposed_tier="cheap",
    )
    assert recommendation.blocked
    assert recommendation.reason == "exogenous-signal-required"


def test_rwr_alone_cannot_cut_review_depth() -> None:
    policy = ModelPolicy.from_tiers(
        {"cheap": "cheap-model", "build": "build-model", "mid": "mid-model", "deep": "deep-model"}
    )
    recommendation = recommend_implement_tier(
        "build",
        proposed_tier="cheap",
        ready_without_rework_rate=1.0,
        exogenous={},
        baseline_exogenous={},
        policy=policy,
        allowed_tiers=("cheap", "build", "mid", "deep"),
        hold_detection_config="detector-v1",
    )
    assert recommendation.blocked
    assert recommendation.reason == "rwr-alone-insufficient"


def test_exogenous_non_regressing_allows_tier_downgrade() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = LearningStore(tmp)
        store.append_from_journal(
            _journal(),
            provenance="live",
            cohort_dimensions={},
            outcomes={
                "readyWithoutRework": True,
                "exogenous": {"postMergeRevertRate": 0.005},
            },
        )
        stats = routing_cohort_stats(store, hold_detection_config="detector-v1")
        policy = ModelPolicy.from_tiers(
            {"cheap": "cheap-model", "build": "build-model", "mid": "mid-model", "deep": "deep-model"}
        )
        recommendation = recommend_tier_from_cohort(
            current_tier="build",
            stats=stats,
            baseline_exogenous={"postMergeRevertRate": 0.01},
            policy=policy,
            allowed_tiers=("cheap", "build", "mid", "deep"),
            proposed_tier="cheap",
        )
        assert not recommendation.blocked
        assert recommendation.recommended_tier == "cheap"
