"""Unit tests for remediation fragment + consumer halt wiring (PRD 079 R13, R14, R10/TR6)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import check_gate_lib as gate  # noqa: E402

_PLUGIN_ROOT = _SCRIPTS.parent / "core"
_FRAGMENT = _PLUGIN_ROOT / "providers" / "host" / "remediation-checks.md"


def test_remediation_fragment_has_provider_sections() -> None:
    text = _FRAGMENT.read_text(encoding="utf-8")
    for section in ("github", "gitlab", "bitbucket", "default"):
        assert f"## {section}" in text


def test_remediation_fragment_github_fg_pat_primary_no_checks_read() -> None:
    text = _FRAGMENT.read_text(encoding="utf-8")
    assert "fine-grained PAT" in text
    assert "Checks" in text
    assert "legacy" in text.lower()
    assert gate.CHECKS_READ_SCOPE_STRING not in text


def test_remediation_surface_violates_checks_read_positive() -> None:
    assert gate.remediation_surface_violates_checks_read(
        "Grant checks:read scope on your token."
    )


def test_remediation_surface_violates_checks_read_prohibitive_allowed() -> None:
    assert not gate.remediation_surface_violates_checks_read(
        "The invalid scope string checks:read MUST NOT appear in any remediation surface."
    )


def test_runtime_remediation_matches_fragment_for_github() -> None:
    fragment = gate.load_checks_remediation(_PLUGIN_ROOT, "github")
    runtime = gate.checks_gate_halt_remediation(
        {"verdict": "blocked", "reasonCode": gate.REASON_HOST_AUTH_REQUIRED},
        plugin_root=_PLUGIN_ROOT,
        provider="github",
    )
    assert runtime == fragment
    assert gate.CHECKS_READ_SCOPE_STRING not in runtime


def test_should_halt_ci_watch_without_poll_only_for_host_auth() -> None:
    assert gate.should_halt_ci_watch_without_poll(
        {"verdict": "blocked", "reasonCode": gate.REASON_HOST_AUTH_REQUIRED}
    )
    assert not gate.should_halt_ci_watch_without_poll(
        {"verdict": "blocked", "reasonCode": gate.REASON_CHECKS_RATE_LIMITED}
    )
    assert not gate.should_halt_ci_watch_without_poll({"verdict": "yellow"})


def test_is_checks_gate_non_retryable_halt() -> None:
    assert gate.is_checks_gate_non_retryable_halt(
        {"verdict": "blocked", "reasonCode": gate.REASON_HOST_AUTH_REQUIRED}
    )
    assert not gate.is_checks_gate_non_retryable_halt(
        {"verdict": "blocked", "reasonCode": gate.REASON_CHECKS_RATE_LIMITED, "retryable": True}
    )


@pytest.mark.parametrize(
    "provider,needle",
    [
        ("github", "fine-grained PAT"),
        ("gitlab", "commit statuses"),
        ("bitbucket", "commit build statuses"),
    ],
)
def test_load_checks_remediation_per_provider(provider: str, needle: str) -> None:
    text = gate.load_checks_remediation(_PLUGIN_ROOT, provider)
    assert needle in text
    assert gate.remediation_surface_violates_checks_read(text) is False
