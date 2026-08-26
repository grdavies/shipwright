"""PRD 332 R4, R5, R11, R12 — CapabilityPromotion registry transitions and metric gates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from capability_promotion import (  # noqa: E402
    CapabilityPromotionError,
    PromotionNotReadyError,
    QualifyingRun,
    STATE_ACTIVE,
    STATE_CANDIDATE,
    STATE_ROLLED_BACK,
    STATE_SHADOW,
    attach_run_from_evidence_ref,
    build_capability_record,
    build_registry,
    build_revision_record,
    evaluate_promotion_readiness,
    promote_revision,
    qualifying_runs_for_promotion,
    read_registry,
    record_qualifying_run,
    rollback_active_revision,
    serialize_registry,
    upsert_revision,
    write_registry,
    FamilyThresholds,
)


def _thresholds(**overrides: float | int) -> FamilyThresholds:
    base = {
        "minQualifyingRuns": 3,
        "maxFalsePositiveRate": 0.05,
        "maxVetoConflictRate": 0.02,
        "minShadowAgreement": 0.85,
    }
    base.update(overrides)
    return FamilyThresholds.from_mapping(base)


def _good_run(run_id: str, *, observed_at: str, agreement: float = 0.9) -> QualifyingRun:
    return QualifyingRun(
        run_id=run_id,
        observed_at=observed_at,
        false_positive_rate=0.01,
        veto_conflict_rate=0.01,
        shadow_agreement=agreement,
        evidence_ref=f"sha256:{'a' * 64}",
        evidence_fresh=True,
    )


def _shadow_revision(*, revision: int = 1, runs: list[QualifyingRun] | None = None) -> dict:
    return build_revision_record(
        revision=revision,
        state=STATE_SHADOW,
        capability_family="triage-intelligence",
        evidence_class="TriageEvidence@v1",
        evidence_ref="sha256:" + ("b" * 64),
        thresholds=_thresholds(),
        qualifying_runs=runs or [],
    )


def test_registry_roundtrip_and_idempotent_upsert(tmp_path: Path) -> None:
    revision = _shadow_revision()
    capability = build_capability_record(
        "triage.recommendation",
        capability_family="triage-intelligence",
        revisions={1: revision},
        active_revision=1,
    )
    registry = build_registry({"triage.recommendation": capability})
    serialized = serialize_registry(registry)
    reparsed = json.loads(serialized)
    assert reparsed["capabilities"]["triage.recommendation"]["activeRevision"] == 1

    path = tmp_path / "registry.json"
    write_registry(path, registry)
    loaded = read_registry(path)
    again = serialize_registry(loaded)
    assert again == serialized

    updated = upsert_revision(loaded, "triage.recommendation", revision)
    assert serialize_registry(updated) == serialized


def test_legal_and_illegal_transitions() -> None:
    registry = build_registry(
        {
            "triage.recommendation": build_capability_record(
                "triage.recommendation",
                capability_family="triage-intelligence",
                revisions={1: _shadow_revision()},
                active_revision=1,
            )
        }
    )

    candidate = build_revision_record(
        revision=1,
        state=STATE_CANDIDATE,
        capability_family="triage-intelligence",
        evidence_class="TriageEvidence@v1",
        evidence_ref="sha256:" + ("c" * 64),
        thresholds=_thresholds(),
    )
    with pytest.raises(PromotionNotReadyError):
        promote_revision(registry, "triage.recommendation", 1, target_state=STATE_CANDIDATE)

    runs = [_good_run(f"run-{idx}", observed_at=f"2026-08-2{idx}T10:00:00Z") for idx in range(3)]
    shadow_with_runs = _shadow_revision(runs=runs)
    registry = upsert_revision(registry, "triage.recommendation", shadow_with_runs, set_active=True)
    registry = promote_revision(registry, "triage.recommendation", 1, target_state=STATE_CANDIDATE)

    active = build_revision_record(
        revision=1,
        state=STATE_ACTIVE,
        capability_family="triage-intelligence",
        evidence_class="TriageEvidence@v1",
        evidence_ref="sha256:" + ("d" * 64),
        thresholds=_thresholds(),
        qualifying_runs=runs,
        prior_active={"revision": 1, "evidenceRef": "sha256:" + ("e" * 64), "state": STATE_ACTIVE},
    )
    registry = upsert_revision(registry, "triage.recommendation", active, set_active=True)

    with pytest.raises(CapabilityPromotionError, match="illegal-transition"):
        promote_revision(registry, "triage.recommendation", 1, target_state=STATE_SHADOW, force=True)


def test_threshold_boundaries_and_insufficient_runs() -> None:
    thresholds = _thresholds(minQualifyingRuns=2, minShadowAgreement=0.8)
    runs = [
        _good_run("run-1", observed_at="2026-08-21T10:00:00Z", agreement=0.79),
        _good_run("run-2", observed_at="2026-08-22T10:00:00Z", agreement=0.95),
    ]
    eligible = qualifying_runs_for_promotion(runs, thresholds)
    assert len(eligible) == 1

    revision = build_revision_record(
        revision=2,
        state=STATE_SHADOW,
        capability_family="triage-intelligence",
        evidence_class="TriageEvidence@v1",
        evidence_ref="sha256:" + ("f" * 64),
        thresholds=thresholds,
        qualifying_runs=runs,
    )
    with pytest.raises(PromotionNotReadyError, match="insufficient-qualifying-runs"):
        evaluate_promotion_readiness(revision, target_state=STATE_CANDIDATE)


def test_stale_evidence_rejection() -> None:
    stale = attach_run_from_evidence_ref(
        run_id="run-stale",
        observed_at="2026-08-21T10:00:00Z",
        false_positive_rate=0.01,
        veto_conflict_rate=0.01,
        shadow_agreement=0.95,
        evidence_ref="stale:sha256:" + ("0" * 64),
    )
    assert stale.evidence_fresh is False
    assert not qualifying_runs_for_promotion([stale], _thresholds())


def test_rollback_restores_prior_active_revision() -> None:
    prior_ref = "sha256:" + ("1" * 64)
    new_ref = "sha256:" + ("2" * 64)
    runs = [_good_run(f"run-{idx}", observed_at=f"2026-08-2{idx}T10:00:00Z") for idx in range(3)]

    rev1 = build_revision_record(
        revision=1,
        state=STATE_ACTIVE,
        capability_family="triage-intelligence",
        evidence_class="TriageEvidence@v1",
        evidence_ref=prior_ref,
        thresholds=_thresholds(),
    )
    rev2 = build_revision_record(
        revision=2,
        state=STATE_ACTIVE,
        capability_family="triage-intelligence",
        evidence_class="TriageEvidence@v1",
        evidence_ref=new_ref,
        thresholds=_thresholds(),
        qualifying_runs=runs,
        prior_active={"revision": 1, "evidenceRef": prior_ref, "state": STATE_ACTIVE},
    )
    registry = build_registry(
        {
            "triage.recommendation": build_capability_record(
                "triage.recommendation",
                capability_family="triage-intelligence",
                revisions={1: rev1, 2: rev2},
                active_revision=2,
            )
        }
    )

    rolled = rollback_active_revision(registry, "triage.recommendation", 2, reason="veto-conflict-regression")
    capability = rolled["capabilities"]["triage.recommendation"]
    assert capability["activeRevision"] == 1
    assert capability["revisions"]["2"]["state"] == STATE_ROLLED_BACK
    assert capability["revisions"]["1"]["state"] == STATE_ACTIVE
    assert capability["revisions"]["1"]["evidenceRef"] == prior_ref


def test_record_qualifying_run_idempotent() -> None:
    registry = build_registry(
        {
            "compression.lossy": build_capability_record(
                "compression.lossy",
                capability_family="context-compression",
                revisions={1: _shadow_revision()},
                active_revision=1,
            )
        }
    )
    run = _good_run("run-a", observed_at="2026-08-21T10:00:00Z")
    once = record_qualifying_run(registry, "compression.lossy", 1, run)
    twice = record_qualifying_run(once, "compression.lossy", 1, run)
    revision = twice["capabilities"]["compression.lossy"]["revisions"]["1"]
    assert len(revision["qualifyingRuns"]) == 1
