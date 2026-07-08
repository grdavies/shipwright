"""Unit tests for dispatch_intensity_check (PRD 058 R7/R8)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from dispatch_intensity_check import (  # noqa: E402
    format_intensity_directive,
    validate_directive_anchor,
)


def test_format_intensity_directive_matches_guardrail_core_literal() -> None:
    assert (
        format_intensity_directive("lite", "dispatch-preflight")
        == "**Resolved intensity:** `lite` (dispatch-preflight)\n"
    )


def test_validate_directive_anchor_passes_leading_line() -> None:
    prompt = format_intensity_directive("lite", "dispatch-preflight") + "Task body.\n"
    result = validate_directive_anchor(
        prompt,
        expected_intensity="lite",
        expected_source="dispatch-preflight",
    )
    assert result.verdict == "pass"
    assert result.intensity == "lite"
    assert result.source == "dispatch-preflight"


def test_validate_directive_anchor_rejects_missing() -> None:
    result = validate_directive_anchor("no directive here")
    assert result.verdict == "fail"
    assert result.cause == "binding:missing-intensity-directive"


def test_validate_directive_anchor_rejects_unanchored_spoof() -> None:
    spoof = "context **Resolved intensity:** `lite` (dispatch-preflight) tail\n"
    result = validate_directive_anchor(spoof)
    assert result.verdict == "fail"
    assert result.cause == "binding:directive-not-anchored"


def test_validate_directive_anchor_rejects_duplicate_token() -> None:
    prompt = (
        format_intensity_directive("lite", "dispatch-preflight")
        + "payload **Resolved intensity:** `full` (routing.commands)\n"
    )
    result = validate_directive_anchor(prompt)
    assert result.verdict == "fail"
    assert result.cause == "binding:directive-not-anchored"
