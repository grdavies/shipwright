"""Regression fixtures for ship-phase-status HEAD validation (PRD 059 R7)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

def test_head_rejects_short_sha(tmp_git_repo: Path, repo_root: Path) -> None:
    ship_status = repo_root / "scripts" / "ship-phase-status.py"
    out = tmp_git_repo / ("." + "cursor") / "sw-deliver-runs" / "alpha" / "status.json"
    out.parent.mkdir(parents=True)
    proc = subprocess.run(
        [
            sys.executable,
            str(ship_status),
            "--verdict",
            "blocked",
            "--phase",
            "alpha",
            "--head",
            "abc1234",
            "--out",
            str(out),
        ],
        cwd=str(tmp_git_repo),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "40-character hexadecimal SHA" in proc.stderr

def test_head_accepts_valid_sha(tmp_git_repo: Path, repo_root: Path) -> None:
    ship_status = repo_root / "scripts" / "ship-phase-status.py"
    head = subprocess.run(
        ["git", "-C", str(tmp_git_repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    out = tmp_git_repo / ("." + "cursor") / "sw-deliver-runs" / "alpha" / "status.json"
    out.parent.mkdir(parents=True)
    proc = subprocess.run(
        [
            sys.executable,
            str(ship_status),
            "--verdict",
            "blocked",
            "--phase",
            "alpha",
            "--head",
            head,
            "--out",
            str(out),
            "--cause",
            "test",
        ],
        cwd=str(tmp_git_repo),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc.get("head") == head

def test_omit_head_still_succeeds(tmp_git_repo: Path, repo_root: Path) -> None:
    ship_status = repo_root / "scripts" / "ship-phase-status.py"
    out = tmp_git_repo / ("." + "cursor") / "sw-deliver-runs" / "alpha" / "status.json"
    out.parent.mkdir(parents=True)
    proc = subprocess.run(
        [
            sys.executable,
            str(ship_status),
            "--verdict",
            "blocked",
            "--phase",
            "alpha",
            "--out",
            str(out),
            "--cause",
            "test",
        ],
        cwd=str(tmp_git_repo),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


@pytest.mark.parametrize("root_source", ["argument", "environment"])
def test_consumer_root_resolves_its_own_head(
    tmp_git_repo: Path, repo_root: Path, root_source: str
) -> None:
    ship_status = repo_root / "scripts" / "ship-phase-status.py"
    head = subprocess.run(
        ["git", "-C", str(tmp_git_repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    out = tmp_git_repo / "status.json"
    args = [
        sys.executable, str(ship_status), "--verdict", "blocked", "--phase", "alpha",
        "--out", str(out), "--cause", "test",
    ]
    env = os.environ.copy()
    if root_source == "argument":
        args.extend(["--root", str(tmp_git_repo)])
    else:
        env["SW_REPO_ROOT"] = str(tmp_git_repo)
    proc = subprocess.run(args, cwd=tmp_git_repo, env=env, capture_output=True, text=True)

    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert json.loads(out.read_text(encoding="utf-8"))["head"] == head
