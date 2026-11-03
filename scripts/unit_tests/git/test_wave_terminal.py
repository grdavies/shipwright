"""Regression fixtures for terminal PR branch validation (PRD 059 R13-R15)."""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.git]


def _load_source_module(repo_root: Path, name: str):
    # Preserve the module object already used by collected test functions so
    # later fault injection patches their actual globals.
    module = importlib.import_module(name)
    assert Path(module.__file__).resolve() == (repo_root / "scripts" / f"{name}.py").resolve()
    return module


def _load_wave_terminal(repo_root: Path):
    return _load_source_module(repo_root, "wave_terminal")


def _load_wave_failure(repo_root: Path):
    return _load_source_module(repo_root, "wave_failure")


@pytest.mark.parametrize("name", ["wave_terminal", "wave_failure"])
def test_wave_loaders_preserve_canonical_import_identity(repo_root: Path, name: str) -> None:
    canonical = importlib.import_module(name)
    paths_before = list(sys.path)
    loader = _load_wave_terminal if name == "wave_terminal" else _load_wave_failure
    assert loader(repo_root) is canonical
    assert sys.modules[name] is canonical
    assert sys.path == paths_before


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
