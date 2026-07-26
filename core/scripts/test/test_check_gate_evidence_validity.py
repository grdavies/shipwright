"""Unit tests for checks evidence validity matrix and host-auth-required (PRD 079 R7, R8, R10, R20)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_CORE_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_CORE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CORE_SCRIPTS))

import check_gate_lib as gate  # noqa: E402

_HEAD_SHA = "abc123def4567890abcdef1234567890abcdef12"
_PR = "42"
_HOST_ERROR_BODY = "Bad credentials: secret-token-xyz-should-not-appear"


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
            "body": _HOST_ERROR_BODY,
            "retryable": False,
        }
    return {"verdict": "fail", "reason": f"unexpected verb {verb}"}


@pytest.mark.parametrize(
    ("transport_class", "expected_reason_code", "retryable", "exit_code"),
    [
        ("auth-denied", gate.REASON_HOST_AUTH_REQUIRED, False, 30),
        ("not-found", gate.REASON_CHECKS_NOT_FOUND, False, 30),
        ("rate-limited", gate.REASON_CHECKS_RATE_LIMITED, True, 37),
        ("inconclusive", gate.REASON_CHECKS_UNAVAILABLE, True, 37),
    ],
)
def test_validity_matrix_transport_class_to_outcome(
    transport_class: str,
    expected_reason_code: str,
    retryable: bool,
    exit_code: int,
) -> None:
    envelope = gate.checks_evidence_from_host_verb(
        {"verdict": "fail", "transportClass": transport_class, "statusCode": 401}
    )
    assert envelope["evidenceValidity"] == gate.EVIDENCE_INVALID
    assert envelope["reasonCode"] == expected_reason_code
    assert envelope["checks"] == []

    plugin_root = gate.resolve_plugin_root(_CORE_SCRIPTS)
    code, payload = gate.gate_blocked_for_invalid_checks_evidence(
        envelope,
        plugin_root=plugin_root,
        provider="github",
        head_sha=_HEAD_SHA,
    )
    assert code == exit_code
    assert payload["verdict"] == "blocked"
    assert payload["reasonCode"] == expected_reason_code
    assert payload.get("retryable") is retryable


def test_malformed_ok_payload_is_invalid_not_empty() -> None:
    envelope = gate.checks_evidence_from_host_verb(
        {"verdict": "ok", "data": {"check_runs": []}}
    )
    assert envelope["evidenceValidity"] == gate.EVIDENCE_INVALID
    assert envelope["reasonCode"] == gate.REASON_CHECKS_MALFORMED
    assert envelope["checks"] == []


def test_valid_empty_list_remains_valid_evidence() -> None:
    envelope = gate.checks_evidence_from_host_verb({"verdict": "ok", "data": []})
    assert envelope["evidenceValidity"] == gate.EVIDENCE_VALID
    assert envelope["reasonCode"] == gate.REASON_CHECKS_OK
    assert envelope["checks"] == []


def test_host_auth_required_uses_remediation_fragment_not_host_body(
    tmp_path: Path,
) -> None:
    envelope = gate.checks_evidence_from_host_verb(
        {
            "verdict": "fail",
            "transportClass": "auth-denied",
            "body": _HOST_ERROR_BODY,
        }
    )
    plugin_root = gate.resolve_plugin_root(_CORE_SCRIPTS)
    _, payload = gate.gate_blocked_for_invalid_checks_evidence(
        envelope,
        plugin_root=plugin_root,
        provider="github",
    )
    assert payload["reasonCode"] == gate.REASON_HOST_AUTH_REQUIRED
    assert _HOST_ERROR_BODY not in payload["reason"]
    assert "fine-grained PAT" in payload["reason"]


def test_run_gate_auth_denied_blocked_exit_30(
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

    exit_code, payload = gate.run_gate(tmp_path, _PR)

    assert exit_code == 30
    assert payload["verdict"] == "blocked"
    assert payload["reasonCode"] == gate.REASON_HOST_AUTH_REQUIRED
    assert payload.get("retryable") is False
    assert _HOST_ERROR_BODY not in payload["reason"]


def test_run_gate_empty_checks_yields_empty_check_set_reason_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg_dir = tmp_path / ".cursor"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "workflow.config.json").write_text(
        json.dumps(_workflow_config()),
        encoding="utf-8",
    )

    def host_side_effect(root: Path, *args: str) -> dict[str, Any]:
        verb = args[0] if args else ""
        if verb == "checks":
            return {"verdict": "ok", "data": []}
        return _host_side_effect(root, *args)

    monkeypatch.setattr(gate, "host_verb", host_side_effect)
    monkeypatch.setattr(
        "host_lib.resolve_provider",
        lambda root: {"verdict": "ok", "provider": "github"},
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
    assert payload["reasonCode"] == gate.REASON_EMPTY_CHECK_SET
    assert payload["reasonCode"] != gate.REASON_HOST_AUTH_REQUIRED
    assert payload["reason"] == "empty check set"


def test_invalid_evidence_short_circuits_before_yellow_review_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg_dir = tmp_path / ".cursor"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "workflow.config.json").write_text(
        json.dumps({**_workflow_config(), "review": {"provider": "coderabbit"}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(gate, "host_verb", lambda root, *args: _host_side_effect(root, *args))
    monkeypatch.setattr(
        "host_lib.resolve_provider",
        lambda root: {"verdict": "ok", "provider": "github"},
    )
    monkeypatch.setattr(
        gate,
        "resolve_review_state",
        lambda *a, **k: (
            {
                "error": False,
                "review_provider": "coderabbit",
                "cr_state": "in-flight",
                "cr_landed": False,
                "cr_reviewed_head": "",
                "cr_status": "absent",
                "cr_marker": False,
                "cr_skipped": False,
                "mins_since": 0,
                "review_landed": False,
                "review_state": "in-flight",
            },
            [],
        ),
    )

    exit_code, payload = gate.run_gate(tmp_path, _PR)

    assert exit_code == 30
    assert payload["verdict"] == "blocked"
    assert payload["reasonCode"] == gate.REASON_HOST_AUTH_REQUIRED
    assert payload["verdict"] != "yellow"
