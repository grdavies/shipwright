"""Regression fixtures for wave_merge discovery (PRD 059 R5/R6/R8)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytestmark = [pytest.mark.git]


def _load_gap_gate(repo_root: Path):
    path = repo_root / "scripts" / "gap-check-gate.py"
    spec = importlib.util.spec_from_file_location("gap_check_gate", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(repo_root / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def _load_wave_merge(repo_root: Path):
    path = repo_root / "scripts" / "wave_merge.py"
    spec = importlib.util.spec_from_file_location("wave_merge", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(repo_root / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def test_gap_check_worktree_only_discovery(tmp_git_repo: Path, repo_root: Path) -> None:
    """Worktree-only gap-check status is discovered without canonical sync (R5)."""
    phase_slug = "phase-gap-discovery"
    head = subprocess.run(
        ["git", "-C", str(tmp_git_repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    wt_name = "phase-wt-only"
    wt_root = tmp_git_repo / ".sw-worktrees" / wt_name
    status_dir = wt_root / ".cursor" / "sw-deliver-runs" / phase_slug
    status_dir.mkdir(parents=True)
    (status_dir / "gap-check.status.json").write_text(
        json.dumps(
            {
                "verdict": "pass",
                "binding": True,
                "head": head,
                "updatedAt": _utc_now(),
            }
        ),
        encoding="utf-8",
    )
    gap_gate = _load_gap_gate(repo_root)
    ok, cause = gap_gate.deliver_gap_check_ok(tmp_git_repo, phase_slug, require_status=True)
    assert ok, cause

def test_gap_check_halt_dominant_over_stale_pass(tmp_git_repo: Path, repo_root: Path) -> None:
    """Fresh halt wins over stale worktree pass via HEAD disambiguation (R6)."""
    phase_slug = "phase-halt-precedence"
    head = subprocess.run(
        ["git", "-C", str(tmp_git_repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    canonical_dir = tmp_git_repo / ".cursor" / "sw-deliver-runs" / phase_slug
    canonical_dir.mkdir(parents=True)
    (canonical_dir / "gap-check.status.json").write_text(
        json.dumps(
            {
                "verdict": "pass",
                "binding": True,
                "head": "0" * 40,
                "updatedAt": "2020-01-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    wt_root = tmp_git_repo / ".sw-worktrees" / "halt-wt"
    halt_dir = wt_root / ".cursor" / "sw-deliver-runs" / phase_slug
    halt_dir.mkdir(parents=True)
    (halt_dir / "gap-check.status.json").write_text(
        json.dumps(
            {
                "verdict": "halt",
                "binding": True,
                "head": head,
                "cause": "scope-fidelity",
                "updatedAt": _utc_now(),
            }
        ),
        encoding="utf-8",
    )
    gap_gate = _load_gap_gate(repo_root)
    ok, cause = gap_gate.deliver_gap_check_ok(tmp_git_repo, phase_slug, require_status=True)
    assert not ok
    assert cause == "scope-fidelity"

def test_wave_merge_head_comparison_unchanged(tmp_git_repo: Path, repo_root: Path) -> None:
    """R8: wave_merge validate_status_sha still uses exact-string equality."""
    from status_integrity import check_status_sha

    wave_merge = _load_wave_merge(repo_root)
    head = subprocess.run(
        ["git", "-C", str(tmp_git_repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    status = {"head": head}
    ok, _ = check_status_sha(status, head)
    assert ok
    with pytest.raises(SystemExit):
        wave_merge.validate_status_sha({"head": head.upper()}, head, "phase")
