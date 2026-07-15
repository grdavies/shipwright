"""PRD 069 R1 — terminal ship-run non-exiting prepare/retro helpers and gate watch."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


import wave_terminal as wt


def test_run_terminal_pr_prepare_dry_run_does_not_exit(repo_root: Path, tmp_path: Path) -> None:
    """Library helper returns outcome without sys.exit (R1)."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "T"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-qm", "init"],
        check=True,
    )
    (tmp_path / ".cursor").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"defaultBaseBranch": "main", "deliver": {"terminal": {"autonomy": "auto"}}}),
        encoding="utf-8",
    )
    state = {
        "verdict": "running",
        "prd_number": "069",
        "target": {"branch": "feat/terminal-prepare", "slug": "terminal-prepare", "type": "feat"},
        "phases": {"1": {"status": "green-merged", "slug": "a"}},
    }
    (tmp_path / ".cursor" / "sw-deliver-state.json").write_text(
        json.dumps(state), encoding="utf-8"
    )

    with patch.object(wt, "is_local_host_mode", return_value=True):
        outcome = wt.run_terminal_pr_prepare(tmp_path, ["--dry-run"], dry_run=True)

    assert isinstance(outcome, wt.TerminalOutcome)
    assert outcome.exit_code == 0
    assert outcome.payload.get("action") == "terminal-local-prepare"
    assert outcome.payload.get("dry_run") is True


def test_ship_run_body_continues_after_prepare(repo_root: Path, tmp_path: Path) -> None:
    """Ship-run reaches push/gate after prepare helper (R1)."""
    calls: list[str] = []

    def _fake_prepare(root: Path, args: list[str], *, dry_run: bool | None = None):
        calls.append("prepare")
        return wt.TerminalOutcome(
            {"verdict": "pass", "action": "terminal-pr-prepare", "terminalPr": {"number": 42}},
            0,
        )

    def _fake_push(args, cwd, check=False):
        calls.append("push")
        return MagicMock(returncode=0, stderr="", stdout="")

    def _fake_gate(root, pr):
        calls.append("gate-watch")
        return 0, {"verdict": "green"}

    state = {
        "verdict": "running",
        "target": {"branch": "feat/ship-run"},
        "phases": {"1": {"status": "green-merged", "slug": "a"}},
        "compoundShip": {"premergeDone": True},
        "terminalPr": {"number": 42},
    }

    with (
        patch.object(wt, "load_state", return_value=state),
        patch.object(wt, "terminal_autonomy_mode", return_value="auto"),
        patch.object(wt, "all_phases_green", return_value=True),
        patch.object(wt, "is_local_host_mode", return_value=False),
        patch.object(wt, "run_terminal_pr_prepare", side_effect=_fake_prepare),
        patch.object(wt, "git_top", return_value=tmp_path),
        patch.object(wt, "remote_name", return_value="origin"),
        patch.object(wt, "git_run", side_effect=_fake_push),
        patch.object(wt, "run_terminal_gate_watch", side_effect=_fake_gate),
        patch.object(wt, "remediation_max_attempts", return_value=3),
        patch.object(wt, "save_state"),
        patch.object(wt, "append_log"),
        patch.object(wt, "terminal_gap_capture_best_effort"),
        pytest.raises(wt.TerminalExit) as excinfo,
    ):
        with wt.terminal_library_mode():
            wt._cmd_terminal_ship_run_body(tmp_path, ["--force"], dry_run=False)

    assert calls == ["prepare", "push", "gate-watch"]
    assert excinfo.value.outcome.payload.get("verdict") == "pass"


def test_run_terminal_gate_watch_delegates_to_watch_ci(repo_root: Path, tmp_path: Path) -> None:
    fake = {
        "verdict": "green",
        "mode": "phase-gate-poll",
        "gateExitCode": 0,
        "gate": {"verdict": "green", "source": "host"},
        "ciWatch": False,
    }
    with patch("watch_ci_lib.watch_ci", return_value=fake):
        ec, gate = wt.run_terminal_gate_watch(tmp_path, "99")
    assert ec == 0
    assert gate.get("verdict") == "green"
    assert gate.get("watchMode") == "phase-gate-poll"
