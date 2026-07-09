"""Regression fixtures for terminal PR branch validation (PRD 059 R13-R15)."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.git]


def _load_wave_terminal(repo_root: Path):
    path = repo_root / "scripts" / "wave_terminal.py"
    spec = importlib.util.spec_from_file_location("wave_terminal", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(repo_root / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def _load_wave_failure(repo_root: Path):
    path = repo_root / "scripts" / "wave_failure.py"
    spec = importlib.util.spec_from_file_location("wave_failure", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(repo_root / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def test_terminal_branch_missing_halts_without_pr(tmp_git_repo: Path, repo_root: Path) -> None:
    """Confirmed-missing target branch fails closed with terminal-branch-missing (R14)."""
    wt = _load_wave_terminal(repo_root)
    target = "feat/missing-terminal-branch"
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "branch", target],
        check=True,
        capture_output=True,
    )
    with patch.object(wt, "probe_remote_ref_exists", return_value=False):
        outcome = wt.classify_target_branch_existence(
            tmp_git_repo, target, "origin", tmp_git_repo
        )
    assert outcome == wt.TERMINAL_BRANCH_ABSENT
    with pytest.raises(SystemExit) as exc:
        wt.halt_terminal_branch_outcome(outcome, target=target)
    assert exc.value.code == 20


def test_terminal_branch_unresolvable_halts_without_pr(tmp_git_repo: Path, repo_root: Path) -> None:
    """Probe-inconclusive branch check fails closed with terminal-branch-unresolvable (R14)."""
    from host_ratelimit import HostProbeInconclusive

    wt = _load_wave_terminal(repo_root)
    target = "feat/unresolvable-terminal-branch"
    subprocess.run(
        ["git", "-C", str(tmp_git_repo), "branch", target],
        check=True,
        capture_output=True,
    )
    with patch.object(
        wt, "probe_remote_ref_exists", side_effect=HostProbeInconclusive("rate-limited")
    ):
        outcome = wt.classify_target_branch_existence(
            tmp_git_repo, target, "origin", tmp_git_repo
        )
    assert outcome == wt.TERMINAL_BRANCH_UNRESOLVABLE
    with pytest.raises(SystemExit) as exc:
        wt.halt_terminal_branch_outcome(outcome, target=target)
    assert exc.value.code == 20


def test_blocker_recovery_commands_for_terminal_causes(repo_root: Path) -> None:
    """Blocker report maps terminal causes to distinct recovery commands (R15)."""
    wf = _load_wave_failure(repo_root)
    missing = wf.blocker_recovery_command("terminal-branch-missing", {}, "feat/demo")
    unresolvable = wf.blocker_recovery_command(
        "terminal-branch-unresolvable", {}, "feat/demo"
    )
    assert "recreate" in missing or "terminal pr prepare" in missing
    assert "host" in unresolvable.lower() or "auth" in unresolvable.lower()
    assert missing != unresolvable
