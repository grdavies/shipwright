#!/usr/bin/env python3
"""ModelPolicy mid insertion and escalation floors (PRD 269 R8/R9)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.cost_telemetry import next_model_tier as telemetry_next_model_tier  # noqa: E402
from model_policy_lib import (  # noqa: E402
    CANONICAL_TIER_ORDER,
    ModelPolicy,
    ensure_mid_tier,
    next_model_tier,
    ordered_tiers,
    preflight_missing_mid,
)
import stabilize_same_stage_lib as same_stage  # noqa: E402


def _load_dispatch_check():
    path = _SCRIPTS / "dispatch-check.py"
    spec = importlib.util.spec_from_file_location("dispatch_check_r8_r9", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TIERS = {
    "cheap": "model-cheap",
    "build": "model-build",
    "mid": "model-mid",
    "deep": "model-deep",
}


def test_canonical_order_includes_mid_between_build_and_deep() -> None:
    assert CANONICAL_TIER_ORDER == ("cheap", "build", "mid", "deep")
    assert ordered_tiers({}) == CANONICAL_TIER_ORDER
    assert ordered_tiers(TIERS).index("mid") == ordered_tiers(TIERS).index("build") + 1
    assert ordered_tiers(TIERS).index("deep") == ordered_tiers(TIERS).index("mid") + 1


def test_next_model_tier_build_low_confidence_returns_mid() -> None:
    assert (
        next_model_tier(
            "build",
            {"low-confidence"},
            allowed_tiers=TIERS,
            tiers=TIERS,
        )
        == "mid"
    )


def test_verifier_disagreement_and_schema_failure_floor_to_deep() -> None:
    assert (
        next_model_tier(
            "build",
            {"verifier-disagreement"},
            allowed_tiers=TIERS,
            tiers=TIERS,
        )
        == "deep"
    )
    assert (
        next_model_tier(
            "build",
            {"schema-failure"},
            allowed_tiers=TIERS,
            tiers=TIERS,
        )
        == "deep"
    )
    assert (
        next_model_tier(
            "cheap",
            {"schema-failure", "low-confidence"},
            allowed_tiers=TIERS,
            tiers=TIERS,
        )
        == "deep"
    )


def test_cost_telemetry_shares_model_policy() -> None:
    assert (
        telemetry_next_model_tier(
            "build",
            {"low-confidence"},
            allowed_tiers=TIERS,
            tiers=TIERS,
        )
        == "mid"
    )
    assert (
        telemetry_next_model_tier(
            "build",
            {"verifier-disagreement"},
            allowed_tiers=TIERS,
            tiers=TIERS,
        )
        == "deep"
    )


def test_unknown_tier_and_unknown_trigger_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown tier"):
        next_model_tier(
            "turbo",
            {"low-confidence"},
            allowed_tiers={"turbo", "deep"},
            tiers=TIERS,
        )
    with pytest.raises(ValueError, match="unsupported escalation trigger"):
        next_model_tier(
            "build",
            {"not-a-trigger"},
            allowed_tiers=TIERS,
            tiers=TIERS,
        )


def test_deep_floor_respects_allowlist() -> None:
    with pytest.raises(PermissionError):
        next_model_tier(
            "build",
            {"schema-failure"},
            allowed_tiers={"cheap", "build", "mid"},
            tiers=TIERS,
        )


def test_missing_mid_defaulted_with_single_preflight() -> None:
    legacy = {"cheap": "a", "build": "b", "deep": "d"}
    advisory = preflight_missing_mid(legacy)
    assert advisory is not None
    assert advisory["advisory"] == "model-policy:missing-mid-defaulted"
    normalized, defaulted = ensure_mid_tier(dict(legacy))
    assert defaulted is True
    assert normalized["mid"] == "b"
    policy = ModelPolicy.from_tiers(normalized)
    assert policy.tier_order == ("cheap", "build", "mid", "deep")
    assert (
        next_model_tier(
            "build",
            {"low-confidence"},
            allowed_tiers=normalized,
            tiers=legacy,
        )
        == "mid"
    )


def test_stabilize_same_stage_uses_model_policy_and_keeps_floors() -> None:
    policy = ModelPolicy.from_tiers(TIERS)
    assert same_stage.escalate_tier("build", policy=policy) == "mid"
    assert same_stage.escalate_tier("mid", policy=policy) == "deep"
    assert same_stage.escalate_tier("deep", policy=policy) is None
    # Inserting mid must not soften deep-floor escalation shared via ModelPolicy.
    assert (
        next_model_tier(
            "build",
            {"verifier-disagreement"},
            allowed_tiers=TIERS,
            tiers=TIERS,
        )
        == "deep"
    )


def test_dispatch_check_normalize_shares_policy() -> None:
    dc = _load_dispatch_check()
    tiers, policy, advisory = dc._normalize_tiers(
        {"cheap": "a", "build": "b", "deep": "d"}
    )
    assert advisory is not None
    assert "mid" in tiers
    assert policy.tier_rank("mid") == policy.tier_rank("build") + 1
    assert policy.tier_rank("deep") > policy.tier_rank("mid")
