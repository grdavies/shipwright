#!/usr/bin/env python3
"""Promotion, demotion, and in-run kill switch fixtures (PRD 270 R2)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.cutover import (  # noqa: E402
    CutoverDriver,
    DemotionRegression,
    InRunKillSwitch,
    IntegrityScopedInputs,
)
from graph.execution_receipts import (  # noqa: E402
    ExecutionReceiptJournal,
    PromotionDemotionEvent,
    evaluate_run_promotion_evidence,
    promotion_evidence_authority,
    record_demotion_event,
    record_promotion_event,
    receipts_digest,
    write_calibration_table,
)
from graph.workflow_library import (  # noqa: E402
    DigestConfirmation,
    PLAN_POLICY_CANONICAL,
    PLAN_POLICY_PROPOSED,
    PlanPolicyPromotionEvidence,
    PromotionPolicyDocument,
    PromotionSample,
    approve_template,
    demote_template_plan_policy,
    gate_plan_policy_promotion,
    promote_template_plan_policy,
    save_template,
)
from unit_tests.graph.test_workflow_library import (  # noqa: E402
    _graph,
    _parameters,
)


def _receipt(verdict: str = "pass") -> dict[str, object]:
    return {
        "model": "build-model",
        "attempts": 1,
        "tokens": {"input": 120, "output": 30},
        "durationMs": 250,
        "inputHashes": {"prompt": "a" * 64},
        "outputHashes": {"result": "b" * 64},
        "verdict": verdict,
        "coverage": {"required": 4, "completed": 4},
    }


def _samples(template_digest: str) -> tuple[PromotionSample, ...]:
    base = {
        "template_digest": template_digest,
        "prediction_error": 0.05,
        "required_capability_regression": False,
        "ready_without_rework": True,
        "command": "sw-deliver",
        "paired_canonical_run_id": "canonical-paired",
        "confidence": 0.99,
        "coverage_score": 1.0,
    }
    return (
        PromotionSample(run_id="run-dogfood-1", stratum="dogfood-deliver", **base),
        PromotionSample(run_id="run-dogfood-2", stratum="dogfood-deliver", **base),
        PromotionSample(
            run_id="run-prod-1",
            stratum="non-dogfood-deliver",
            **base,
        ),
    )


def _test_policy() -> PromotionPolicyDocument:
    return PromotionPolicyDocument(
        min_sample_size=3,
        confidence_level=0.95,
        demotion_exposure_window_seconds=0,
    )


def _evidence(
    template_digest: str,
    *,
    authorizer: str = "workflow-library-promotion-gate",
) -> PlanPolicyPromotionEvidence:
    return PlanPolicyPromotionEvidence(
        samples=_samples(template_digest),
        authorizer=authorizer,
        confirmation=DigestConfirmation(
            command="sw-deliver",
            digest=template_digest,
            confirmed_by="fixture-human",
            confirmed_at="2026-08-14T00:00:00+00:00",
        ),
        receipts_digest="abc" * 21 + "a",
        calibration_digest="def" * 21 + "d",
    )


def _save_and_approve(library: Path) -> str:
    save_template(
        _graph(),
        name="promotion-workflow",
        root=library,
        parameters=_parameters(),
    )
    approve_template("promotion-workflow", actor="fixture-human", root=library)
    document = (library / "promotion-workflow.json").read_text(encoding="utf-8")
    assert "fixture-human" in document
    from graph.workflow_library import load_template, _template_digest

    loaded = load_template("promotion-workflow", root=library)
    return _template_digest(loaded)


def test_gate_plan_policy_promotion_requires_sample_floor_and_strata(
    tmp_path: Path,
) -> None:
    digest = "a" * 64
    evidence = _evidence(digest)
    gate = gate_plan_policy_promotion(
        evidence,
        target_policy=PLAN_POLICY_PROPOSED,
        template_digest=digest,
    )
    assert gate.passed is True

    thin = PlanPolicyPromotionEvidence(
        samples=evidence.samples[:1],
        authorizer=evidence.authorizer,
        confirmation=evidence.confirmation,
    )
    blocked = gate_plan_policy_promotion(
        thin,
        target_policy=PLAN_POLICY_PROPOSED,
        template_digest=digest,
    )
    assert blocked.passed is False
    assert any("sample floor" in reason for reason in blocked.reasons)


def test_promote_template_plan_policy_proposed_then_canonical(tmp_path: Path) -> None:
    library = tmp_path / ".sw" / "workflows"
    digest = _save_and_approve(library)
    evidence = _evidence(digest)

    promote_template_plan_policy(
        "promotion-workflow",
        evidence,
        target_policy=PLAN_POLICY_PROPOSED,
        root=library,
        policy=_test_policy(),
    )
    promote_template_plan_policy(
        "promotion-workflow",
        evidence,
        target_policy=PLAN_POLICY_CANONICAL,
        root=library,
        policy=_test_policy(),
    )

    loaded = (library / "promotion-workflow.json").read_text(encoding="utf-8")
    assert '"stage": "canonical"' in loaded
    assert "canonicalAdoptedDigest" in loaded


def test_demote_template_plan_policy_drops_proposed(tmp_path: Path) -> None:
    library = tmp_path / ".sw" / "workflows"
    digest = _save_and_approve(library)
    evidence = _evidence(digest)
    promote_template_plan_policy(
        "promotion-workflow",
        evidence,
        target_policy=PLAN_POLICY_PROPOSED,
        root=library,
        policy=_test_policy(),
    )
    demote_template_plan_policy(
        "promotion-workflow",
        reason="prediction error regression",
        actor="operator",
        root=library,
    )
    loaded = (library / "promotion-workflow.json").read_text(encoding="utf-8")
    assert '"stage": "canonical"' in loaded
    assert "canonicalAdoptedDigest" not in loaded


def test_cutover_kill_switch_and_demotion(tmp_path: Path) -> None:
    driver = CutoverDriver()
    driver.promote_plan_policy(
        target_policy=PLAN_POLICY_PROPOSED,
        authorizer="graph-runtime-cutover",
        promoted_at="2026-08-14T00:00:00+00:00",
    )
    assert driver.effective_plan_policy() == PLAN_POLICY_PROPOSED

    driver.activate_kill_switch(
        actor="operator",
        activated_at="2026-08-14T00:01:00+00:00",
    )
    assert isinstance(driver.kill_switch, InRunKillSwitch)
    assert driver.effective_plan_policy() == PLAN_POLICY_CANONICAL
    with pytest.raises(PermissionError, match="kill switch"):
        driver.promote_plan_policy(
            target_policy=PLAN_POLICY_PROPOSED,
            authorizer="graph-runtime-cutover",
            promoted_at="2026-08-14T00:02:00+00:00",
        )

    record = driver.demote_on_regression(
        DemotionRegression(human_rework=True),
        actor="operator",
        demoted_at="2026-08-14T00:03:00+00:00",
        integrity=IntegrityScopedInputs(
            receipts_digest="abc" * 21 + "a",
            calibration_digest="def" * 21 + "d",
        ),
        observed_receipts_digest="abc" * 21 + "a",
        observed_calibration_digest="def" * 21 + "d",
    )
    assert record.plan_policy == PLAN_POLICY_CANONICAL
    assert "human_rework" in record.reasons


def test_execution_receipts_record_promotion_and_demotion(tmp_path: Path) -> None:
    journal = ExecutionReceiptJournal.for_run(tmp_path / "store", "deliver-run-1")
    journal.record("verify", "deliver-run-1:verify", _receipt())
    journal.write_telemetry(
        {"terminalVerdict": "ready", "humanRework": False},
    )
    calibration = write_calibration_table(
        journal,
        {"bucket": "quick", "sampleCount": 3},
    )
    evidence = evaluate_run_promotion_evidence(
        journal,
        "deliver-run-1",
        calibration_table=calibration["calibration"],
    )
    assert evidence.coverage_sufficient is True
    assert evidence.successful_history is True
    assert promotion_evidence_authority(evidence) is True

    promotion = record_promotion_event(
        journal,
        PromotionDemotionEvent(
            event_type="promotion",
            run_id="deliver-run-1",
            plan_policy=PLAN_POLICY_PROPOSED,
            ready_without_rework=True,
            coverage_sufficient=True,
            evidence_authority=True,
            authorizer="workflow-library-promotion-gate",
        ),
    )
    assert promotion["policyEvent"]["eventType"] == "promotion"

    demotion = record_demotion_event(
        journal,
        PromotionDemotionEvent(
            event_type="demotion",
            run_id="deliver-run-1",
            plan_policy=PLAN_POLICY_CANONICAL,
            ready_without_rework=False,
            coverage_sufficient=True,
            evidence_authority=False,
            reasons=("human_rework",),
        ),
    )
    assert demotion["policyEvent"]["eventType"] == "demotion"
    assert receipts_digest(journal)
