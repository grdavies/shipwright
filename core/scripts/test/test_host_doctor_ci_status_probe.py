"""Unit tests for host-doctor CI-status capability probe (PRD 079 R11, R12)."""

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

from host_doctor_lib import (  # noqa: E402
    capability_from_checks_envelope,
    ci_status_is_capable,
    probe_ci_status_capability,
)
import planning_deliver_gate as pdg  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HEAD_SHA = "abc123def4567890abcdef1234567890abcdef12"


def test_capability_from_checks_envelope_ok_is_capable() -> None:
    assert (
        capability_from_checks_envelope(
            {"evidenceValidity": "valid", "transportClass": "ok", "reasonCode": "checks-ok"},
            provider="github",
        )
        == "capable"
    )


def test_capability_from_checks_envelope_auth_denied_is_denied() -> None:
    assert (
        capability_from_checks_envelope(
            {
                "evidenceValidity": "invalid",
                "transportClass": "auth-denied",
                "reasonCode": "host-auth-required",
            },
            provider="github",
        )
        == "denied"
    )


def test_capability_from_checks_envelope_inconclusive_not_capable() -> None:
    capability = capability_from_checks_envelope(
        {
            "evidenceValidity": "invalid",
            "transportClass": "inconclusive",
            "reasonCode": "checks-unavailable",
        },
        provider="github",
    )
    assert capability == "inconclusive"
    assert not ci_status_is_capable({"capability": capability})


def test_probe_local_provider_is_capable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "host_doctor_lib.resolve_provider",
        lambda _root: {"verdict": "ok", "provider": "none", "tokenEnv": ""},
    )
    result = probe_ci_status_capability(_REPO_ROOT)
    assert result["capability"] == "capable"
    assert result["reasonCode"] == "local-evidence"


def test_probe_missing_token_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "host_doctor_lib.resolve_provider",
        lambda _root: {
            "verdict": "ok",
            "provider": "github",
            "tokenEnv": "GITHUB_TOKEN",
            "tokenPresent": False,
        },
    )
    monkeypatch.setattr("host_doctor_lib.token_present", lambda _env: False)
    result = probe_ci_status_capability(_REPO_ROOT)
    assert result["capability"] == "denied"
    assert result["reasonCode"] == "missing-token"


def test_probe_auth_denied_checks_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "host_doctor_lib.resolve_provider",
        lambda _root: {
            "verdict": "ok",
            "provider": "github",
            "tokenEnv": "GITHUB_TOKEN",
        },
    )
    monkeypatch.setattr("host_doctor_lib.token_present", lambda _env: True)
    monkeypatch.setattr("host_doctor_lib.git_head_sha", lambda _root: _HEAD_SHA)
    monkeypatch.setattr(
        "host_doctor_lib.host_checks_evidence",
        lambda *_args, **_kwargs: {
            "evidenceValidity": "invalid",
            "transportClass": "auth-denied",
            "reasonCode": "host-auth-required",
            "checks": [],
        },
    )
    result = probe_ci_status_capability(_REPO_ROOT)
    assert result["capability"] == "denied"
    assert result["reasonCode"] == "host-auth-required"


def test_probe_rate_limited_is_inconclusive_not_capable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "host_doctor_lib.resolve_provider",
        lambda _root: {
            "verdict": "ok",
            "provider": "github",
            "tokenEnv": "GITHUB_TOKEN",
        },
    )
    monkeypatch.setattr("host_doctor_lib.token_present", lambda _env: True)
    monkeypatch.setattr("host_doctor_lib.git_head_sha", lambda _root: _HEAD_SHA)
    monkeypatch.setattr(
        "host_doctor_lib.host_checks_evidence",
        lambda *_args, **_kwargs: {
            "evidenceValidity": "invalid",
            "transportClass": "rate-limited",
            "reasonCode": "checks-rate-limited",
            "checks": [],
        },
    )
    result = probe_ci_status_capability(_REPO_ROOT)
    assert result["capability"] == "inconclusive"
    assert not ci_status_is_capable(result)


def test_deliver_entry_halts_on_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "host_doctor_lib.probe_ci_status_capability",
        lambda _root: {"capability": "denied", "provider": "github", "reasonCode": "missing-token"},
    )
    with pytest.raises(SystemExit) as exc:
        pdg.enforce_ci_status_capability_deliver(_REPO_ROOT)
    assert exc.value.code == pdg.CI_STATUS_DENIED_EXIT


def test_deliver_entry_passes_inconclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"capability": "inconclusive", "provider": "github", "reasonCode": "checks-unavailable"}
    monkeypatch.setattr("host_doctor_lib.probe_ci_status_capability", lambda _root: payload)
    assert pdg.enforce_ci_status_capability_deliver(_REPO_ROOT) == payload


def test_host_doctor_emits_ci_status_without_token_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import importlib.util
    import io
    from contextlib import redirect_stdout

    spec = importlib.util.spec_from_file_location("host_doctor", _CORE_SCRIPTS / "host-doctor.py")
    assert spec is not None and spec.loader is not None
    host_doctor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(host_doctor)

    monkeypatch.setattr(
        host_doctor,
        "probe_ci_status_capability",
        lambda _root: {
            "capability": "denied",
            "provider": "github",
            "reasonCode": "host-auth-required",
            "tokenEnv": "GITHUB_TOKEN",
        },
    )

    def fake_check_output(cmd: list[str], *, text: bool) -> str:
        if "resolve" in cmd:
            return json.dumps(
                {
                    "verdict": "ok",
                    "provider": "github",
                    "remote": "origin",
                    "remoteUrl": "https://github.com/example/repo",
                }
            )
        if "token-status" in cmd:
            return json.dumps({"present": True, "tokenEnv": "GITHUB_TOKEN"})
        raise AssertionError(cmd)

    monkeypatch.setattr(host_doctor.subprocess, "check_output", fake_check_output)
    buf = io.StringIO()
    with redirect_stdout(buf):
        host_doctor.main(["--root", str(tmp_path)])
    payload = json.loads(buf.getvalue())
    assert payload["ciStatus"]["capability"] == "denied"
    assert "ci-status-denied" in payload["warnings"]
    serialized = json.dumps(payload)
    assert "ghp_" not in serialized
    assert "github_pat_" not in serialized
