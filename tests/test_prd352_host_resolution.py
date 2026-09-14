"""PRD 352 phase 3 — host resolution and qualification (R10–R13, TR3)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "scripts")]

from core.adapters.host_resolver import (  # noqa: E402
    AUTH_REVOKED,
    AUTH_VALID,
    DestinationValidationError,
    QualifiedHost,
    detect_runtime_host_id,
    requalify,
    resolve,
)


def test_qualified_host_fields() -> None:
    host = resolve(host_id="cursor", repo_root=REPO, installed_version="2.15.0")
    assert isinstance(host, QualifiedHost)
    assert host.host_id == "cursor"
    assert host.surface_adapter == "cursor"
    assert host.installed_version == "2.15.0"
    assert "invoke_workflow" in host.capabilities
    assert host.auth_status == AUTH_VALID


def test_detect_runtime_host_id_legacy_env() -> None:
    assert detect_runtime_host_id({"CLAUDE_PLUGIN_ROOT": "/tmp/claude"}) == "claude-code"
    assert detect_runtime_host_id({"CURSOR_AGENT": "1"}) == "cursor"


def test_detect_platform_routes_through_resolver(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["SW_SETUP_PLATFORM"] = "cursor"
    env.pop("SW_HOST_AUTH_STATUS", None)
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "detect-platform.py"), "--json"],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["platform"] == "cursor"
    assert payload["surface_adapter"] == "cursor"
    assert payload["auth_status"] == AUTH_VALID


def test_missing_capability_fail_closed() -> None:
    with pytest.raises(DestinationValidationError) as exc:
        resolve(
            host_id="cursor",
            required_capabilities=["not-a-real-capability"],
            repo_root=REPO,
        )
    payload = exc.value.as_dict()
    assert payload["error"] == "destination:missing-capability"
    assert "Enable capability" in payload["remediation"]


def test_revoked_auth_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SW_HOST_AUTH_STATUS", AUTH_REVOKED)
    with pytest.raises(DestinationValidationError) as exc:
        resolve(host_id="cursor", repo_root=REPO)
    payload = exc.value.as_dict()
    assert payload["error"] == "destination:auth-revoked"
    assert "Re-authenticate" in payload["remediation"]


def test_requalify_is_live_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    first = requalify(host_id="cursor", repo_root=REPO, installed_version="1.0.0")
    monkeypatch.setenv("SW_HOST_AUTH_STATUS", AUTH_REVOKED)
    with pytest.raises(DestinationValidationError) as exc:
        requalify(host_id="cursor", repo_root=REPO)
    assert exc.value.code == "destination:auth-revoked"
    assert first.auth_status == AUTH_VALID
