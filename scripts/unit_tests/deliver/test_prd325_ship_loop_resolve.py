"""PRD 325 phase 5 — ship_loop resolver + dispatch env (R8, R9)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import wave_deliver_loop as wdl
from sw_scripts_resolve import CONSUMER_NO_PLUGIN_ERROR, ScriptsResolveError


def test_run_ship_loop_drive_uses_resolve_script(repo_root: Path) -> None:
    wt = repo_root
    env = {"SW_PHASE_MODE": "1", "PYTHONPATH": str(repo_root / "scripts")}
    ec, data = wdl.run_ship_loop_drive(wt, "fixture-phase", env)
    assert ec != 0 or data.get("verdict") != "blocked"
    assert data.get("error") != "ship-loop:empty-output"


def test_run_ship_loop_drive_blocked_on_resolver_error(tmp_path: Path) -> None:
    with patch.object(
        wdl,
        "resolve_script",
        side_effect=ScriptsResolveError(CONSUMER_NO_PLUGIN_ERROR),
    ):
        ec, data = wdl.run_ship_loop_drive(tmp_path, "x", {})
    assert ec == 20
    assert data["verdict"] == "blocked"
    assert data["error"] == CONSUMER_NO_PLUGIN_ERROR
    assert data.get("remediation") == CONSUMER_NO_PLUGIN_ERROR


def test_ship_loop_env_absolute_pythonpath(repo_root: Path, tmp_path: Path) -> None:
    wt = tmp_path / "phase-wt"
    wt.mkdir()
    state = {
        "source_task_list": "tasks.md",
        "phaseWorktrees": {"5": {"path": str(wt)}},
    }
    scripts_root = repo_root / "scripts"
    env = wdl.ship_loop_env_for_phase(state, "5", "ship-loop", scripts_root=scripts_root)
    assert env["PYTHONPATH"] == str(scripts_root.resolve())
    assert env["PYTHONPATH"] != "scripts"


def test_build_ship_dispatch_child_env_scrubs_ambient_phase_keys() -> None:
    parent = {
        "SW_PHASE_MODE": "1",
        "SW_PHASE_SLUG": "leaked",
        "SW_RUN_DIR": "/tmp/leaked",
        "PATH": "/bin",
    }
    child = wdl.build_ship_dispatch_child_env(
        {"SW_PHASE_MODE": "1", "SW_PHASE_SLUG": "bound", "PYTHONPATH": "/abs/scripts"},
        parent=parent,
    )
    assert child["SW_PHASE_SLUG"] == "bound"
    assert child["PYTHONPATH"] == "/abs/scripts"
    assert "SW_RUN_DIR" not in child


def test_ensure_phase_worktree_provisions_once(repo_root: Path, tmp_path: Path) -> None:
    state: dict = {"phaseWorktrees": {}, "runId": "deliver-test-run"}
    wt = tmp_path / "provisioned"
    wt.mkdir()

    def fake_run_wave(_root: Path, *args: str) -> tuple[int, dict]:
        assert args[0] == "phase"
        assert args[1] == "provision"
        return 0, {"path": str(wt), "name": "provisioned"}

    with patch.object(wdl, "run_wave", side_effect=fake_run_wave):
        with patch.object(wdl, "save_state"):
            with patch("planning_progress.provision_deliver_hierarchy", return_value={"verdict": "ok"}):
                resolved = wdl._ensure_phase_worktree_for_dispatch(repo_root, state, "5")
    assert resolved == wt

    call_count = 0

    def counting_run_wave(_root: Path, *args: str) -> tuple[int, dict]:
        nonlocal call_count
        call_count += 1
        return 0, {"path": str(wt)}

    state["phaseWorktrees"] = {"5": {"path": str(wt)}}
    with patch.object(wdl, "run_wave", side_effect=counting_run_wave):
        again = wdl._ensure_phase_worktree_for_dispatch(repo_root, state, "5")
    assert again == wt
    assert call_count == 0
