"""Regression tests: denied primary checks must not reach green via secondary evidence (PRD 079 R17)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

_CORE_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_CORE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CORE_SCRIPTS))

import check_gate_lib as gate  # noqa: E402

_HEAD_SHA = "abc123def4567890abcdef1234567890abcdef12"
_PR = "42"

_GREEN_SECONDARY: gate.ChecksEvidenceEnvelope = {
    "evidenceValidity": gate.EVIDENCE_VALID,
    "transportClass": "ok",
    "reasonCode": gate.REASON_CHECKS_OK,
    "checks": [{"name": "ci", "state": "SUCCESS", "conclusion": "SUCCESS"}],
}

_DENIED_PRIMARY: gate.ChecksEvidenceEnvelope = {
    "evidenceValidity": gate.EVIDENCE_INVALID,
    "transportClass": "auth-denied",
    "reasonCode": gate.REASON_HOST_AUTH_REQUIRED,
    "checks": [],
}


def _workflow_config() -> dict[str, Any]:
    return {
        "host": {"provider": "github"},
        "review": {"provider": "none"},
        "checks": {"treatNeutralAsPass": True, "neutralAllowlist": []},
    }


def _host_side_effect(root: Path, *args: str) -> dict[str, Any]:
    verb = args[0] if args else ""
    if verb == "resolve-pr-for-branch":
        return {"verdict": "ok", "data": [{"number": _PR}]}
    if verb == "pr-view":
        return {
            "verdict": "ok",
            "data": {
                "headRefOid": _HEAD_SHA,
                "mergeable": "MERGEABLE",
                "mergeStateStatus": "CLEAN",
            },
        }
    if verb == "repo-meta":
        return {"verdict": "ok", "data": {"nameWithOwner": "owner/repo"}}
    if verb == "review-threads":
        return {"verdict": "ok", "data": {"unresolved": 0, "actionable": 0}}
    if verb == "checks":
        return {
            "verdict": "fail",
            "verb": "checks",
            "provider": "github",
            "transportClass": "auth-denied",
            "statusCode": 401,
            "reason": "auth-denied",
            "retryable": False,
        }
    return {"verdict": "fail", "reason": f"unexpected verb {verb}"}


def test_secondary_source_registry_covers_known_providers() -> None:
    assert "github-statusCheckRollup" in gate.SECONDARY_CHECKS_EVIDENCE_SOURCES
    assert "github-actions-runs" in gate.SECONDARY_CHECKS_EVIDENCE_SOURCES
    assert "gitlab-pipelines" in gate.SECONDARY_CHECKS_EVIDENCE_SOURCES
    assert gate.PRIMARY_CHECKS_EVIDENCE_SOURCE == "checks-verb"


@pytest.mark.parametrize(
    "primary",
    [
        _DENIED_PRIMARY,
        {
            "evidenceValidity": gate.EVIDENCE_INVALID,
            "transportClass": "not-found",
            "reasonCode": gate.REASON_CHECKS_NOT_FOUND,
            "checks": [],
        },
        {
            "evidenceValidity": gate.EVIDENCE_INVALID,
            "transportClass": "rate-limited",
            "reasonCode": gate.REASON_CHECKS_RATE_LIMITED,
            "checks": [],
        },
    ],
)
def test_may_consult_secondary_false_when_primary_invalid(
    primary: gate.ChecksEvidenceEnvelope,
) -> None:
    assert gate.may_consult_secondary_checks_evidence(primary) is False


def test_may_consult_secondary_false_even_when_primary_valid_under_r17_policy() -> None:
    valid_primary: gate.ChecksEvidenceEnvelope = {
        "evidenceValidity": gate.EVIDENCE_VALID,
        "transportClass": "ok",
        "reasonCode": gate.REASON_CHECKS_OK,
        "checks": [],
    }
    assert gate.may_consult_secondary_checks_evidence(valid_primary) is False


def test_resolve_checks_evidence_skips_secondary_when_primary_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gate, "host_checks_evidence", lambda *a, **k: dict(_DENIED_PRIMARY))
    secondary_called = False

    def _secondary(*args: Any, **kwargs: Any) -> gate.ChecksEvidenceEnvelope | None:
        nonlocal secondary_called
        secondary_called = True
        return _GREEN_SECONDARY

    monkeypatch.setattr(gate, "checks_evidence_from_secondary_sources", _secondary)

    envelope = gate.resolve_checks_evidence_for_gate(
        tmp_path,
        pr=_PR,
        sha=_HEAD_SHA,
    )

    assert envelope["evidenceValidity"] == gate.EVIDENCE_INVALID
    assert envelope["reasonCode"] == gate.REASON_HOST_AUTH_REQUIRED
    assert secondary_called is False


def test_resolve_checks_evidence_never_returns_secondary_while_policy_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid_primary: gate.ChecksEvidenceEnvelope = {
        "evidenceValidity": gate.EVIDENCE_VALID,
        "transportClass": "ok",
        "reasonCode": gate.REASON_CHECKS_OK,
        "checks": [{"name": "primary", "state": "SUCCESS"}],
    }
    monkeypatch.setattr(gate, "host_checks_evidence", lambda *a, **k: dict(valid_primary))
    monkeypatch.setattr(
        gate,
        "checks_evidence_from_secondary_sources",
        lambda *a, **k: _GREEN_SECONDARY,
    )

    envelope = gate.resolve_checks_evidence_for_gate(tmp_path, pr=_PR, sha=_HEAD_SHA)

    assert envelope["checks"][0]["name"] == "primary"


def test_run_gate_denied_primary_cannot_reach_green_via_secondary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg_dir = tmp_path / ".cursor"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "workflow.config.json").write_text(
        json.dumps(_workflow_config()),
        encoding="utf-8",
    )

    monkeypatch.setattr(gate, "host_verb", lambda root, *args: _host_side_effect(root, *args))
    monkeypatch.setattr(
        "host_lib.resolve_provider",
        lambda root: {"verdict": "ok", "provider": "github"},
    )
    monkeypatch.setattr(
        gate,
        "checks_evidence_from_secondary_sources",
        lambda *a, **k: _GREEN_SECONDARY,
    )
    monkeypatch.setattr(
        gate,
        "resolve_review_state",
        lambda *a, **k: (
            {
                "error": False,
                "review_provider": "none",
                "cr_state": "off",
                "cr_landed": True,
                "cr_reviewed_head": "",
                "cr_status": "off",
                "cr_marker": False,
                "cr_skipped": False,
                "mins_since": 0,
                "review_landed": True,
                "review_state": "off",
            },
            [],
        ),
    )

    exit_code, payload = gate.run_gate(tmp_path, _PR)

    assert exit_code == 30
    assert payload["verdict"] == "blocked"
    assert payload["reasonCode"] == gate.REASON_HOST_AUTH_REQUIRED
    assert payload["verdict"] != "green"
    assert payload.get("checkCount", 0) == 0


def test_run_gate_clean_merge_state_does_not_override_denied_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """statusCheckRollup-equivalent CLEAN merge state must not authorize merge (R17)."""
    cfg_dir = tmp_path / ".cursor"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "workflow.config.json").write_text(
        json.dumps(_workflow_config()),
        encoding="utf-8",
    )

    def host_side_effect(root: Path, *args: str) -> dict[str, Any]:
        verb = args[0] if args else ""
        if verb == "pr-view":
            return {
                "verdict": "ok",
                "data": {
                    "headRefOid": _HEAD_SHA,
                    "mergeable": "MERGEABLE",
                    "mergeStateStatus": "CLEAN",
                },
            }
        return _host_side_effect(root, *args)

    monkeypatch.setattr(gate, "host_verb", host_side_effect)
    monkeypatch.setattr(
        "host_lib.resolve_provider",
        lambda root: {"verdict": "ok", "provider": "github"},
    )

    exit_code, payload = gate.run_gate(tmp_path, _PR)

    assert exit_code == 30
    assert payload["reasonCode"] == gate.REASON_HOST_AUTH_REQUIRED
    assert payload["verdict"] != "green"
