"""Pytest port of run_planning_visibility_acceptance_fixtures.py (PRD 054 W4 behavioral)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

import planning_visibility as pv

_PKG = "scripts/unit_tests/planning"
_HARNESS = "harness_planning_visibility_acceptance.py"


def _load_harness(repo_root: Path):
    path = repo_root / _PKG / _HARNESS
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("harness_planning_visibility_acceptance", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def test_planning_visibility_acceptance_behavior(repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in sw_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo_root)
    mod = _load_harness(repo_root)
    assert int(mod.main()) == 0


def test_planning_visibility_acceptance_harness_present(repo_root: Path) -> None:
    """R16 — harness module must exist (fail-closed if port regresses)."""
    assert (repo_root / _PKG / _HARNESS).is_file()


def _write_minimal_config(root: Path) -> None:
    cfg_dir = root / ".cursor"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "projectId": "acme-demo",
        "defaultBaseBranch": "main",
        "host": {
            "provider": "github",
            "remote": "origin",
            "ssrfAllowlist": ["api.github.com"],
        },
        "planning": {
            "store": {
                "backend": "file-store",
                "storeLocation": {"mode": "same-repo"},
            }
        },
    }
    (cfg_dir / "workflow.config.json").write_text(json.dumps(payload), encoding="utf-8")


def test_probe_inconclusive_resolves_all_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R8 — ambiguous host-API probe fails closed to all-private."""
    _write_minimal_config(tmp_path)
    monkeypatch.setattr(
        pv,
        "git_remote_url",
        lambda *a, **k: "https://github.com/acme/public-repo.git",
    )
    monkeypatch.setattr(pv, "_github_repo_private", lambda *a, **k: None)
    monkeypatch.setattr(
        pv,
        "_store_host_privacy_probe",
        lambda *a, **k: {"verdict": "ok", "storeHostPrivacy": "not-applicable", "source": "backend-not-issue-store"},
    )

    result = pv.resolve_default_profile(tmp_path)

    assert result["visibilityTier"] == "all-private"
    assert result["privacyAck"]["required"] is True
    assert result["remoteProbe"]["source"] == "probe-inconclusive"
    assert result["remoteProbe"]["remoteVisibility"] == "absent"


def test_no_remote_and_unprobeable_remote_still_specs_public(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R8 — genuinely absent or unprobeable remotes keep specs-public default."""
    _write_minimal_config(tmp_path)
    monkeypatch.setattr(
        pv,
        "_store_host_privacy_probe",
        lambda *a, **k: {"verdict": "ok", "storeHostPrivacy": "not-applicable", "source": "backend-not-issue-store"},
    )

    monkeypatch.setattr(pv, "git_remote_url", lambda *a, **k: None)
    no_remote = pv.resolve_default_profile(tmp_path)
    assert no_remote["visibilityTier"] == "specs-public"
    assert no_remote["privacyAck"]["required"] is False
    assert no_remote["remoteProbe"]["source"] == "no-remote"

    monkeypatch.setattr(pv, "git_remote_url", lambda *a, **k: "git@unknown-host:acme/demo.git")
    unprobeable = pv.resolve_default_profile(tmp_path)
    assert unprobeable["visibilityTier"] == "specs-public"
    assert unprobeable["privacyAck"]["required"] is False
    assert unprobeable["remoteProbe"]["source"] == "unprobeable-remote"
