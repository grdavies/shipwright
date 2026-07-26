"""Integration tests: checks evidence must not be erased via host_data or [] (PRD 079 R21)."""

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
from host_invoke import host_checks_evidence  # noqa: E402

_HEAD_SHA = "abc123def4567890abcdef1234567890abcdef12"
_PR = "42"


def _workflow_config() -> dict[str, Any]:
    return {
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


def test_checks_evidence_from_auth_denied_host_verb() -> None:
    payload = {
        "verdict": "fail",
        "transportClass": "auth-denied",
        "statusCode": 401,
    }
    envelope = gate.checks_evidence_from_host_verb(payload)
    assert envelope["evidenceValidity"] == gate.EVIDENCE_INVALID
    assert envelope["transportClass"] == "auth-denied"
    assert envelope["reasonCode"] == gate.REASON_HOST_AUTH_REQUIRED
    assert envelope["checks"] == []


def test_host_invoke_checks_evidence_preserves_auth_denied() -> None:
    with patch("host_invoke.host_verb") as mock_verb:
        mock_verb.return_value = {
            "verdict": "fail",
            "transportClass": "auth-denied",
            "statusCode": 403,
        }
        envelope = host_checks_evidence(Path("/tmp"), "checks", number="1", sha=_HEAD_SHA)
    assert envelope["evidenceValidity"] == gate.EVIDENCE_INVALID
    assert envelope["reasonCode"] == gate.REASON_HOST_AUTH_REQUIRED


def test_run_gate_auth_denied_checks_yields_host_auth_required(
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
    assert payload["evidenceValidity"] == gate.EVIDENCE_INVALID
    assert payload["transportClass"] == "auth-denied"
    assert payload.get("retryable") is False
