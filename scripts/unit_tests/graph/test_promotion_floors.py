#!/usr/bin/env python3
"""PRD 272 phase-5 promotion hard floors, pairing, and policy digest tests (R15)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.workflow_library import (  # noqa: E402
    DigestConfirmation,
    PLAN_POLICY_CANONICAL,
    PLAN_POLICY_PROPOSED,
    PROMOTION_CONFIDENCE_FLOOR,
    PROMOTION_SAMPLE_FLOOR,
    PlanPolicyPromotionEvidence,
    PromotionPolicyDocument,
    PromotionSample,
    WorkflowLibraryError,
    approve_template,
    auto_promote_allowed,
    demote_template_plan_policy,
    gate_plan_policy_promotion,
    promote_template_plan_policy,
    promotion_policy_digest,
    save_template,
)
from unit_tests.graph.test_workflow_library import (  # noqa: E402
    _graph,
    _parameters,
)


def _sample(
    *,
    run_id: str,
    stratum: str,
    template_digest: str,
    paired_canonical_run_id: str,
    prediction_error: float = 0.05,
    confidence: float = 1.0,
    perfect_score: bool = False,
) -> PromotionSample:
    return PromotionSample(
        run_id=run_id,
        stratum=stratum,
        template_digest=template_digest,
        prediction_error=prediction_error,
        required_capability_regression=False,
        ready_without_rework=True,
        command="sw-deliver",
        paired_canonical_run_id=paired_canonical_run_id,
        confidence=confidence,
        perfect_score=perfect_score,
    )


def _paired_samples(template_digest: str) -> tuple[PromotionSample, ...]:
    rows: list[PromotionSample] = []
    for index in range(PROMOTION_SAMPLE_FLOOR):
        canonical_id = f"run-canonical-{index}"
        for stratum in ("dogfood-deliver", "non-dogfood-deliver"):
            rows.append(
                _sample(
                    run_id=canonical_id,
                    stratum=stratum,
                    template_digest=template_digest,
                    paired_canonical_run_id=canonical_id,
                )
            )
            rows.append(
                _sample(
                    run_id=f"run-proposed-{stratum}-{index}",
                    stratum=stratum,
                    template_digest=template_digest,
                    paired_canonical_run_id=canonical_id,
                )
            )
    return tuple(rows)


def _evidence(
    template_digest: str,
    *,
    samples: tuple[PromotionSample, ...] | None = None,
) -> PlanPolicyPromotionEvidence:
    return PlanPolicyPromotionEvidence(
        samples=samples or _paired_samples(template_digest),
        authorizer="workflow-library-promotion-gate",
        confirmation=DigestConfirmation(
            command="sw-deliver",
            digest=template_digest,
            confirmed_by="fixture-human",
            confirmed_at="2026-08-14T00:00:00+00:00",
        ),
        receipts_digest="abc" * 21 + "a",
        calibration_digest="def" * 21 + "d",
    )


def _policy() -> PromotionPolicyDocument:
    return PromotionPolicyDocument(
        min_sample_size=PROMOTION_SAMPLE_FLOOR,
        confidence_level=PROMOTION_CONFIDENCE_FLOOR,
    )


def _save_and_approve(library: Path) -> str:
    save_template(
        _graph(),
        name="promotion-floors-workflow",
        root=library,
        parameters=_parameters(),
    )
    approve_template("promotion-floors-workflow", actor="fixture-human", root=library)
    from graph.workflow_library import _template_digest, load_template

    loaded = load_template("promotion-floors-workflow", root=library)
    return _template_digest(loaded)


def test_promotion_hard_floors_and_policy_digest(tmp_path: Path) -> None:
    digest = "a" * 64
    policy = _policy()
    evidence = _evidence(digest)
    gate = gate_plan_policy_promotion(
        evidence,
        target_policy=PLAN_POLICY_PROPOSED,
        template_digest=digest,
        policy=policy,
    )
    assert gate.passed is True
    assert gate.policy_digest == promotion_policy_digest(policy)

    thin = PlanPolicyPromotionEvidence(
        samples=evidence.samples[:2],
        authorizer=evidence.authorizer,
        confirmation=evidence.confirmation,
    )
    blocked = gate_plan_policy_promotion(
        thin,
        target_policy=PLAN_POLICY_PROPOSED,
        template_digest=digest,
        policy=policy,
    )
    assert blocked.passed is False
    assert any("sample floor" in reason for reason in blocked.reasons)
    assert auto_promote_allowed(len(thin.samples)) is False
    assert auto_promote_allowed(PROMOTION_SAMPLE_FLOOR) is True

    low_confidence = _sample(
        run_id="run-low-confidence",
        stratum="dogfood-deliver",
        template_digest=digest,
        paired_canonical_run_id="run-canonical-low",
        confidence=PROMOTION_CONFIDENCE_FLOOR - 0.1,
    )
    confidence_blocked = gate_plan_policy_promotion(
        PlanPolicyPromotionEvidence(
            samples=_paired_samples(digest) + (low_confidence,),
            authorizer=evidence.authorizer,
            confirmation=evidence.confirmation,
        ),
        target_policy=PLAN_POLICY_PROPOSED,
        template_digest=digest,
        policy=policy,
    )
    assert confidence_blocked.passed is False
    assert any("confidence" in reason for reason in confidence_blocked.reasons)

    unpaired = tuple(
        _sample(
            run_id=f"run-unpaired-{index}",
            stratum="dogfood-deliver",
            template_digest=digest,
            paired_canonical_run_id="",
        )
        for index in range(PROMOTION_SAMPLE_FLOOR)
    )
    pairing_blocked = gate_plan_policy_promotion(
        PlanPolicyPromotionEvidence(
            samples=unpaired,
            authorizer=evidence.authorizer,
            confirmation=evidence.confirmation,
        ),
        target_policy=PLAN_POLICY_PROPOSED,
        template_digest=digest,
        policy=policy,
    )
    assert pairing_blocked.passed is False
    assert any("pairing" in reason for reason in pairing_blocked.reasons)


def test_promote_records_policy_digest_and_demotion_latency(tmp_path: Path) -> None:
    library = tmp_path / ".sw" / "workflows"
    digest = _save_and_approve(library)
    evidence = _evidence(digest)
    policy = _policy()
    promote_template_plan_policy(
        "promotion-floors-workflow",
        evidence,
        target_policy=PLAN_POLICY_PROPOSED,
        root=library,
        promoted_at="2026-08-14T00:00:00+00:00",
        policy=policy,
    )
    loaded = (library / "promotion-floors-workflow.json").read_text(encoding="utf-8")
    assert promotion_policy_digest(policy) in loaded
    assert '"policyDigest"' in loaded

    with pytest.raises(WorkflowLibraryError, match="latency window"):
        demote_template_plan_policy(
            "promotion-floors-workflow",
            reason="prediction error regression",
            actor="operator",
            root=library,
            demoted_at="2026-08-14T00:30:00+00:00",
            in_flight_runs=0,
        )

    with pytest.raises(WorkflowLibraryError, match="in-flight"):
        demote_template_plan_policy(
            "promotion-floors-workflow",
            reason="prediction error regression",
            actor="operator",
            root=library,
            demoted_at="2026-08-14T02:00:00+00:00",
            in_flight_runs=1,
        )

    demote_template_plan_policy(
        "promotion-floors-workflow",
        reason="prediction error regression",
        actor="operator",
        root=library,
        demoted_at="2026-08-14T02:00:00+00:00",
        in_flight_runs=0,
    )
    demoted = (library / "promotion-floors-workflow.json").read_text(encoding="utf-8")
    assert '"stage": "canonical"' in demoted
