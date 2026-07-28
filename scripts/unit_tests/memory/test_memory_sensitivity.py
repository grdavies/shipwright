"""PRD 082 R29 — sensitivity tiers and monotonic declassification fixtures."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_envelope_upgrade as upgrade  # noqa: E402
import memory_sensitivity as sens  # noqa: E402


def test_missing_and_unparseable_default_to_strictest_tier() -> None:
    assert sens.resolve_sensitivity(None) == sens.STRICTEST_TIER
    assert sens.resolve_sensitivity("") == sens.STRICTEST_TIER
    assert sens.resolve_sensitivity("   ") == sens.STRICTEST_TIER
    assert sens.resolve_sensitivity("not-a-tier") == sens.STRICTEST_TIER
    assert sens.resolve_sensitivity(42) == sens.STRICTEST_TIER


def test_raising_restriction_is_accepted_without_approval() -> None:
    result = sens.set_sensitivity("public", "secret")
    assert result["verdict"] == "pass"
    assert result["toTier"] == "secret"
    assert result["action"] == "raise"


def test_ungated_lowering_is_refused() -> None:
    result = sens.set_sensitivity("secret", "public")
    assert result["verdict"] == "fail"
    assert result["cause"] == "declassification:approval-required"
    assert result["humanGate"] == sens.HUMAN_GATE_COMMAND


def test_gated_declassification_requires_matching_approval() -> None:
    root = Path.cwd()
    approval = {
        "stableId": "mem-test",
        "approver": "operator",
        "fromTier": "secret",
        "toTier": "internal",
    }
    result = sens.set_sensitivity(
        "secret",
        "internal",
        approval=approval,
        root=root,
        scope="pytest",
    )
    assert result["verdict"] == "pass"
    assert result["toTier"] == "internal"
    assert result["journalEntry"]["verdict"] == "pass"


def test_sensitivity_cannot_widen_destination_policy() -> None:
    assert sens.effective_tier("public", "secret") == "secret"
    assert sens.effective_tier("internal", "private") == "private"
    assert sens.effective_tier("secret", "public") == "secret"
    assert sens.effective_tier("public", "private") == "private"


def test_v1_upgrade_migrates_missing_sensitivity_to_strictest() -> None:
    v1 = {
        "schemaVersion": 1,
        "id": "legacy-no-sens",
        "project": "shipwright",
        "category": "learning",
        "status": "active",
        "content": "note body",
    }
    envelope = upgrade.upgrade_v1_to_v2(v1)
    assert envelope["sensitivity"] == sens.STRICTEST_TIER


def test_envelope_setter_refuses_ungated_declassification() -> None:
    envelope = {
        "stableId": "mem-x",
        "sensitivity": "private",
    }
    result = sens.set_envelope_sensitivity(envelope, "public")
    assert result["verdict"] == "fail"
    assert "envelope" not in result
