"""Documentation surface tests for PRD 079 phase 12 (R22–R25)."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import check_gate_lib as gate  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WATCH_CI = _REPO_ROOT / "core" / "commands" / "sw-watch-ci.md"
_GITHUB_MD = _REPO_ROOT / "core" / "providers" / "host" / "github.md"
_CAPABILITIES = _REPO_ROOT / "core" / "providers" / "host" / "CAPABILITIES.md"
_COMMANDS = _REPO_ROOT / "docs" / "guides" / "commands.md"
_REMEDIATION = _REPO_ROOT / "core" / "providers" / "host" / "remediation-checks.md"


def test_sw_watch_ci_docs_halt_on_host_auth_required() -> None:
    """R22 — verdict→next-step documents host-auth-required halt + remediation."""
    text = _WATCH_CI.read_text(encoding="utf-8")
    assert "host-auth-required" in text
    assert "remediation-checks.md" in text
    assert "halt without CI poll" in text.lower() or "halt without ci poll" in text.lower()
    assert "do not poll" in text.lower()


def test_github_md_auth_remediation_link() -> None:
    """R23 — FG PAT Checks: Read primary; classic repo legacy; no checks:read as valid scope."""
    text = _GITHUB_MD.read_text(encoding="utf-8")
    assert "fine-grained PAT" in text
    assert "Checks: Read" in text
    assert "legacy" in text.lower()
    assert "remediation-checks.md" in text
    assert gate.CHECKS_READ_SCOPE_STRING not in text


def test_capabilities_md_checks_evidence_contract() -> None:
    """R24 — statusCode, classifier outcomes, auth-denied payload, evidenceValidity fields."""
    text = _CAPABILITIES.read_text(encoding="utf-8")
    assert "statusCode" in text
    assert "evidenceValidity" in text
    assert "transportClass" in text
    assert "reasonCode" in text
    for outcome in ("ok", "auth-denied", "not-found", "rate-limited", "inconclusive"):
        assert outcome in text
    assert "host-auth-required" in text


def test_commands_md_auth_required_not_pollable() -> None:
    """R25 — unavailable Checks capability is remediation halt, not pollable CI."""
    text = _COMMANDS.read_text(encoding="utf-8")
    assert "host-auth-required" in text
    assert "remediation halt" in text.lower()
    assert "do not poll" in text.lower()
    assert "remediation-checks.md" in text
