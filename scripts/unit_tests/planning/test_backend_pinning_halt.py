"""PRD 080 phase 15 — mid-run backend-control pinning halt (R8)."""

from __future__ import annotations

import json
import subprocess
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
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/pinning-fixture.git"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_mid_run_disable_flip_halts_pinned_run(tmp_git_repo: Path) -> None:
    _seed_remote(tmp_git_repo)
    cfg = _issue_store_cfg()
    _write_cfg(tmp_git_repo, cfg)
    pinned = pbc.control_state_snapshot(tmp_git_repo, cfg)
    assert pinned["forcedFallback"] is False
    assert ps.resolve_effective_backend(tmp_git_repo, cfg)["effective"] == "issue-store"

    flipped = pbc.cmd_disable(tmp_git_repo, set_by="operator", reason="mid-wave rollback")
    assert flipped["verdict"] == "ok"

    check = pbc.validate_control_pin(tmp_git_repo, cfg, pinned)
    assert check["verdict"] == "fail"
    assert check["halt"] == "backend-control-changed"
    assert check["reason"] == "mid-wave rollback"
    assert ps.resolve_effective_backend(tmp_git_repo, cfg).get("killSwitch") is True
