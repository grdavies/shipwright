"""PRD 332 R2, R6, R10, R13 — TriageEvidence@v1 contract, freshness, and redaction tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from triage_evidence import (  # noqa: E402
    EVIDENCE_VERSION,
    SAFETY_CLASS_ADVISORY,
    SAFETY_CLASS_SAFETY_FLOOR,
    SIGNAL_ARCHITECTURE_RADAR,
    SIGNAL_DECISION_GRAPH,
    SIGNAL_EXPLORATION_FINDINGS,
    SIGNAL_STATE_ABSENT,
    SIGNAL_VERIFICATION_CAPABILITY,
    SIGNAL_WORKFLOW_HISTORY,
    adapt_architecture_radar_signal,
    adapt_decision_graph_uncertainty_signal,
    adapt_exploration_findings_signal,
    adapt_verification_capability_signal,
    adapt_workflow_history_signal,
    aggregate_project_intelligence_for_triage,
    aggregate_weighted_advisory,
    build_explain,
    build_signal,
    build_triage_evidence,
    canonical_json,
    collect_project_intelligence_signals,
    compute_payload_digest,
    compute_producer_signature,
    invalidate_signal,
    parse_triage_evidence,
    safety_floor_precedence,
    serialize_triage_evidence,
    signal_disposition,
    TriageEvidenceError,
    TriageEvidenceSecretError,
    validate_freshness_envelope,
    write_triage_evidence,
)


def _future_iso(minutes: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _past_iso(minutes: int = 30) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_triage_evidence_v1_roundtrip_weighted_signals() -> None:
    """triage-evidence-v1-roundtrip: stable canonical explain output."""
    signals = [
        build_signal("architecture-radar", weight=0.6, value=0.8, producer_path="scripts/architecture_radar.py"),
        build_signal("workflow-history", weight=0.4, value=0.5, producer_path="scripts/workflow_intelligence.py"),
    ]
    document = build_triage_evidence(signals)
    serialized = serialize_triage_evidence(document)
    reparsed = parse_triage_evidence(json.loads(serialized))
    assert reparsed["version"] == EVIDENCE_VERSION
    assert canonical_json(reparsed["explain"]["components"]) == canonical_json(document["explain"]["components"])
    again = serialize_triage_evidence(reparsed)
    assert again == serialized


def test_absent_versus_zero_semantics() -> None:
    """Missing signals remain absent — never coerced to numeric zero."""
    absent = build_signal(
        "exploration-findings",
        weight=0.5,
        state=SIGNAL_STATE_ABSENT,
        absent_reason="producer-unavailable",
    )
    assert absent["state"] == SIGNAL_STATE_ABSENT
    assert "value" not in absent
    assert signal_disposition(absent) == "absent"

    with pytest.raises(TriageEvidenceError, match="absent-signal-cannot-carry-value"):
        build_signal(
            "exploration-findings",
            weight=0.5,
            state=SIGNAL_STATE_ABSENT,
            absent_reason="bad",
            payload_extra={"value": 0.0},
        )


def test_evidence_digest_envelope_rejects_clock_only() -> None:
    """evidence-digest-envelope: producer-bound digest validation rejects clock-only freshness."""
    envelope = {
        "observedAt": _future_iso(),
        "producerPath": "scripts/architecture_radar.py",
        "producerSignature": "sha256:" + compute_producer_signature("scripts/architecture_radar.py"),
        "invalidation": {"state": "valid"},
    }
    with pytest.raises(TriageEvidenceError, match="clock-only-freshness-rejected"):
        validate_freshness_envelope(envelope, compute_payload_digest({"id": "x", "value": 1.0}))


def test_digest_mismatch_invalidates() -> None:
    signal = build_signal("decision-graph", weight=0.5, value=0.7)
    freshness = dict(signal["freshness"])
    freshness["digest"] = "sha256:" + ("0" * 64)
    signal["freshness"] = freshness
    assert signal_disposition(signal) == "invalidated"


def test_expiry_boundary_stale() -> None:
    signal = build_signal(
        "verification-capability",
        weight=0.3,
        value=0.9,
        expires_at=_past_iso(),
    )
    assert signal_disposition(signal) == "stale"


def test_producer_signature_validation() -> None:
    signal = build_signal("architecture-radar", weight=0.5, value=0.6, producer_path="scripts/architecture_radar.py")
    envelope = signal["freshness"]
    validate_freshness_envelope(envelope, compute_payload_digest(signal))

    envelope["producerSignature"] = "sha256:" + ("f" * 64)
    with pytest.raises(TriageEvidenceError, match="producer-signature-mismatch"):
        validate_freshness_envelope(envelope, compute_payload_digest(signal))


def test_fresh_safety_floor_beats_stale_advisory() -> None:
    """evidence-freshness-invalidation: fresh safety input outranks stale advisory."""
    safety = build_signal(
        "safety-kernel",
        weight=1.0,
        value=1.0,
        safety_class=SAFETY_CLASS_SAFETY_FLOOR,
    )
    advisory = build_signal(
        "advisory-rank",
        weight=0.9,
        value=0.95,
        safety_class=SAFETY_CLASS_ADVISORY,
        expires_at=_past_iso(),
    )
    assert safety_floor_precedence(safety, advisory) == "safety-floor"
    assert signal_disposition(advisory) == "stale"


def test_secret_refusal_before_persistence(tmp_path: Path) -> None:
    secret = "ghp_" + "A" * 36
    signal = build_signal("leaky-producer", weight=0.5, value=0.5, payload_extra={"note": secret})
    document = build_triage_evidence([signal])
    out = tmp_path / "evidence.json"
    with pytest.raises(TriageEvidenceSecretError):
        write_triage_evidence(out, document)


def test_invalidation_metadata_blocks_freshness() -> None:
    signal = build_signal("history", weight=0.4, value=0.5)
    invalidated = invalidate_signal(signal, reason="digest-rotated")
    assert signal_disposition(invalidated) == "invalidated"


def test_build_explain_stable_ordering() -> None:
    first = build_signal("alpha", weight=0.2, value=0.1)
    second = build_signal("beta", weight=0.8, value=0.9)
    explain = build_explain([second, first])
    ids = [item["id"] for item in explain["components"]]
    assert ids == ["alpha", "beta"]


def test_multi_producer_aggregation_stable_ordering() -> None:
    """Many-signal weighting with deterministic contribution ordering."""
    signals = [
        build_signal(SIGNAL_ARCHITECTURE_RADAR, weight=0.6, value=0.8),
        build_signal(SIGNAL_WORKFLOW_HISTORY, weight=0.4, value=0.5),
        build_signal(SIGNAL_DECISION_GRAPH, weight=0.5, value=0.2),
    ]
    aggregation = aggregate_weighted_advisory(signals)
    assert aggregation["rankingClass"] == "advisory"
    assert aggregation["advisoryScore"] == pytest.approx(0.52, rel=1e-3)
    contribution_ids = [item["id"] for item in aggregation["contributions"]]
    assert contribution_ids == sorted(contribution_ids)


def test_missing_exploration_emits_absent_not_zero() -> None:
    def _absent_exploration(_root: Path, **kwargs: object) -> dict[str, Any]:
        return build_signal(
            SIGNAL_EXPLORATION_FINDINGS,
            weight=0.5,
            state=SIGNAL_STATE_ABSENT,
            absent_reason="exploration-findings-missing",
        )

    signals = collect_project_intelligence_signals(
        Path("."),
        adapters={
            "architecture-radar": lambda root, **kwargs: build_signal(
                SIGNAL_ARCHITECTURE_RADAR, weight=0.6, value=0.5
            ),
            "workflow-history": lambda root, **kwargs: build_signal(
                SIGNAL_WORKFLOW_HISTORY, weight=0.4, value=0.5
            ),
            "exploration-findings": _absent_exploration,
            "decision-graph": lambda root, **kwargs: build_signal(
                SIGNAL_DECISION_GRAPH, weight=0.5, value=0.3
            ),
            "verification-capability": lambda root, **kwargs: build_signal(
                SIGNAL_VERIFICATION_CAPABILITY,
                weight=0.3,
                value=1.0,
                safety_class=SAFETY_CLASS_SAFETY_FLOOR,
            ),
        },
    )
    exploration = next(item for item in signals if item["id"] == SIGNAL_EXPLORATION_FINDINGS)
    assert exploration["state"] == SIGNAL_STATE_ABSENT
    aggregation = aggregate_weighted_advisory(signals)
    assert SIGNAL_EXPLORATION_FINDINGS in aggregation["absent"]
    assert aggregation["advisoryScore"] is not None
    assert "value" not in exploration


def test_stale_history_excluded_from_advisory_score() -> None:
    fresh = build_signal(SIGNAL_ARCHITECTURE_RADAR, weight=0.6, value=0.8)
    stale = build_signal(
        SIGNAL_WORKFLOW_HISTORY,
        weight=0.4,
        value=0.9,
        expires_at=_past_iso(),
    )
    aggregation = aggregate_weighted_advisory([fresh, stale])
    assert aggregation["advisoryScore"] == pytest.approx(0.8, rel=1e-3)
    assert SIGNAL_WORKFLOW_HISTORY in aggregation["excludedStale"]


def test_decision_graph_uncertainty_contribution() -> None:
    signal = build_signal(SIGNAL_DECISION_GRAPH, weight=0.5, value=0.75)
    aggregation = aggregate_weighted_advisory([signal])
    contribution = aggregation["contributions"][0]
    assert contribution["contribution"] == pytest.approx(0.375, rel=1e-3)


def test_safety_veto_precedence_in_aggregation() -> None:
    safety = build_signal(
        SIGNAL_VERIFICATION_CAPABILITY,
        weight=0.3,
        value=0.0,
        safety_class=SAFETY_CLASS_SAFETY_FLOOR,
    )
    advisory = build_signal(SIGNAL_ARCHITECTURE_RADAR, weight=0.6, value=0.95)
    aggregation = aggregate_weighted_advisory([safety, advisory])
    assert aggregation["rankingClass"] == "safety-floor"
    assert aggregation["safetyFloorScore"] == 0.0
    assert aggregation["advisoryScore"] == pytest.approx(0.95, rel=1e-3)


def test_aggregate_project_intelligence_document_includes_explain_block(tmp_path: Path) -> None:
    document = aggregate_project_intelligence_for_triage(
        tmp_path,
        unit_id="332-prd-project-intelligence-triage-and-capability-promotion",
        adapters={
            "architecture-radar": lambda root, **kwargs: build_signal(
                SIGNAL_ARCHITECTURE_RADAR, weight=0.6, value=0.5
            ),
            "workflow-history": lambda root, **kwargs: build_signal(
                SIGNAL_WORKFLOW_HISTORY, weight=0.4, value=0.5
            ),
            "exploration-findings": lambda root, **kwargs: build_signal(
                SIGNAL_EXPLORATION_FINDINGS,
                weight=0.5,
                state=SIGNAL_STATE_ABSENT,
                absent_reason="exploration-findings-missing",
            ),
            "decision-graph": lambda root, **kwargs: build_signal(
                SIGNAL_DECISION_GRAPH, weight=0.5, value=0.25
            ),
            "verification-capability": lambda root, **kwargs: build_signal(
                SIGNAL_VERIFICATION_CAPABILITY,
                weight=0.3,
                value=1.0,
                safety_class=SAFETY_CLASS_SAFETY_FLOOR,
            ),
        },
    )
    assert document["version"] == EVIDENCE_VERSION
    assert "aggregation" in document["explain"]
    assert document["explain"]["aggregation"]["rankingClass"] == "safety-floor"
    parse_triage_evidence(document)
