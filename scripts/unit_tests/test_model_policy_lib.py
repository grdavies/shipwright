"""Unit tests for shared ModelPolicy (PRD 269 R8/R9)."""
from __future__ import annotations

import pytest

import model_policy_lib as policy


FULL_TIERS = {
    "cheap": "model-cheap",
    "build": "model-build",
    "mid": "model-mid",
    "deep": "model-deep",
}


def test_ordered_tiers_inserts_mid_between_build_and_deep() -> None:
    tiers = {"cheap": "a", "build": "b", "deep": "d"}
    assert policy.ordered_tiers(tiers) == ("cheap", "build", "mid", "deep")


def test_next_model_tier_low_confidence_steps_to_mid() -> None:
    assert policy.next_model_tier(
        "build",
        {"low-confidence"},
        allowed_tiers=FULL_TIERS,
        tiers=FULL_TIERS,
    ) == "mid"


def test_next_model_tier_schema_failure_jumps_to_deep() -> None:
    assert policy.next_model_tier(
        "build",
        {"schema-failure"},
        allowed_tiers=FULL_TIERS,
        tiers=FULL_TIERS,
    ) == "deep"


def test_next_model_tier_verifier_disagreement_jumps_to_deep() -> None:
    assert policy.next_model_tier(
        "cheap",
        {"verifier-disagreement"},
        allowed_tiers=FULL_TIERS,
        tiers=FULL_TIERS,
    ) == "deep"


def test_next_model_tier_unknown_tier_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown tier"):
        policy.next_model_tier(
            "mystery",
            {"low-confidence"},
            allowed_tiers={"mystery"},
            tiers=FULL_TIERS,
        )


def test_next_model_tier_deep_floor_respects_allowlist() -> None:
    with pytest.raises(PermissionError):
        policy.next_model_tier(
            "build",
            {"schema-failure"},
            allowed_tiers={"cheap", "build", "mid"},
            tiers=FULL_TIERS,
        )


def test_preflight_missing_mid_defaults_from_build() -> None:
    advisory = policy.preflight_missing_mid({"cheap": "a", "build": "b", "deep": "d"})
    assert advisory is not None
    assert advisory["advisory"] == "model-policy:missing-mid-defaulted"
    tiers, defaulted = policy.ensure_mid_tier({"cheap": "a", "build": "b", "deep": "d"})
    assert defaulted is True
    assert tiers["mid"] == "b"


def test_model_policy_escalate_one_step_uses_config_order() -> None:
    model_policy = policy.ModelPolicy.from_tiers(FULL_TIERS)
    assert model_policy.escalate_one_step("build") == "mid"
    assert model_policy.escalate_one_step("mid") == "deep"
    assert model_policy.escalate_one_step("deep") is None
