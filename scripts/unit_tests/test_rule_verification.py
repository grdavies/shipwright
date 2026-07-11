"""Unit tests for rule_verification_lib (PRD 064 R7/R8)."""
from __future__ import annotations

import rule_verification_lib as lib


def test_sweep_disabled_by_default():
    cfg = lib.resolve_sweep_config({})
    assert cfg["enabled"] is False


def test_evaluate_verification_promotion_ready():
    verifier = {"ruleId": "r1", "verdict": "supported"}
    skeptic = {"ruleId": "r1", "verdict": "pass"}
    out = lib.evaluate_verification(verifier, skeptic)
    assert out["promotionReady"] is True
    assert out["humanGateRequired"] is True


def test_evaluate_verification_blocks_on_skeptic_fail():
    verifier = {"ruleId": "r1", "verdict": "supported"}
    skeptic = {"ruleId": "r1", "verdict": "fail"}
    out = lib.evaluate_verification(verifier, skeptic)
    assert out["promotionReady"] is False


def test_synthesize_sweep_halts_on_violation():
    results = [{"ruleId": "r1", "verdict": "violation", "repeatViolation": True}]
    out = lib.synthesize_sweep(results)
    assert out["verdict"] == "halt"
