"""PRD 080 phase 15 — backend-control resolver precedence parity (R8)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_backend_control as pbc
import planning_store as ps


def _issue_store_cfg() -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": "planning",
            }
        },
        "host": {"provider": "github"},
    }


def _write_cfg(repo: Path, cfg: dict[str, Any]) -> None:
    path = repo / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _seed_remote(repo: Path) -> None:
    subprocess = __import__("subprocess")
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/resolver-fixture.git"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_no_record_uses_configured_backend(tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_remote(tmp_git_repo)
    cfg = _issue_store_cfg()
    _write_cfg(tmp_git_repo, cfg)
    monkeypatch.delenv(ps.KILL_SWITCH_ENV, raising=False)
    resolved = ps.resolve_effective_backend(tmp_git_repo, cfg)
    assert resolved["effective"] == "issue-store"
    assert resolved.get("killSwitch") is None
    assert resolved.get("fallback") is False


def test_disable_record_forces_file_store_default(tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_remote(tmp_git_repo)
    cfg = _issue_store_cfg()
    _write_cfg(tmp_git_repo, cfg)
    monkeypatch.delenv(ps.KILL_SWITCH_ENV, raising=False)
    out = pbc.cmd_disable(tmp_git_repo, set_by="operator", reason="wave rollback")
    assert out["verdict"] == "ok"
    resolved = ps.resolve_effective_backend(tmp_git_repo, cfg)
    assert resolved["effective"] == "in-repo-public"
    assert resolved.get("killSwitch") is True
    assert resolved.get("fallbackReason") == "kill-switch"


def test_explicit_backend_override_bypasses_disable_record(tmp_git_repo: Path) -> None:
    _seed_remote(tmp_git_repo)
    cfg = _issue_store_cfg()
    _write_cfg(tmp_git_repo, cfg)
    assert pbc.cmd_disable(tmp_git_repo, set_by="operator", reason="wave rollback")["verdict"] == "ok"
    resolved = ps.resolve_effective_backend(tmp_git_repo, cfg, override="issue-store")
    assert resolved["effective"] == "issue-store"
    assert resolved.get("killSwitch") is None


def test_closeout_override_bypasses_disable_record(tmp_git_repo: Path) -> None:
    _seed_remote(tmp_git_repo)
    cfg = _issue_store_cfg()
    _write_cfg(tmp_git_repo, cfg)
    assert pbc.cmd_disable(tmp_git_repo, set_by="operator", reason="wave rollback")["verdict"] == "ok"
    layer = pbc.resolve_control_layer(tmp_git_repo, cfg, override="issue-store", closeout_override=True)
    assert layer["layer"] == "explicit-backend-override"
    assert layer["forcedFallback"] is False


def test_worktree_state_precedence_over_disable_record(tmp_git_repo: Path) -> None:
    _seed_remote(tmp_git_repo)
    cfg = _issue_store_cfg()
    _write_cfg(tmp_git_repo, cfg)
    state = tmp_git_repo / ".cursor" / "sw-worktree-state.json"
    state.write_text(json.dumps({"backendControl": {"forcedFallback": True}}), encoding="utf-8")
    layer = pbc.resolve_control_layer(tmp_git_repo, cfg)
    assert layer["layer"] == "worktree-state"
    assert layer["forcedFallback"] is True


def test_session_state_precedence_over_disable_record(tmp_git_repo: Path) -> None:
    _seed_remote(tmp_git_repo)
    cfg = _issue_store_cfg()
    _write_cfg(tmp_git_repo, cfg)
    state = tmp_git_repo / ".cursor" / "sw-deliver-state.fixture.json"
    state.write_text(json.dumps({"backendControl": {"forcedFallback": True}}), encoding="utf-8")
    layer = pbc.resolve_control_layer(tmp_git_repo, cfg)
    assert layer["layer"] == "session-state"
    assert layer["forcedFallback"] is True


def test_legacy_kill_switch_shim_cannot_change_behavior(
    tmp_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_remote(tmp_git_repo)
    cfg = _issue_store_cfg()
    _write_cfg(tmp_git_repo, cfg)
    monkeypatch.setenv(ps.KILL_SWITCH_ENV, "1")
    without_record = ps.resolve_effective_backend(tmp_git_repo, cfg)
    assert without_record["effective"] == "issue-store"
    assert without_record.get("killSwitch") is None
    assert pbc.legacy_kill_switch_env_shim()
    assert pbc.cmd_disable(tmp_git_repo, set_by="operator", reason="wave rollback")["verdict"] == "ok"
    with_record = ps.resolve_effective_backend(tmp_git_repo, cfg)
    assert with_record["effective"] == "in-repo-public"
    assert with_record.get("killSwitch") is True
    assert with_record.get("legacyShimWarnings")
