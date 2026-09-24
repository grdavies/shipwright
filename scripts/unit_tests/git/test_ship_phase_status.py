"""Regression fixtures for ship-phase-status HEAD validation (PRD 059 R7)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ship_phase_steps import SHIP_CHAIN

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
    head = subprocess.run(
        ["git", "-C", str(tmp_git_repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    out = tmp_git_repo / ("." + "cursor") / "sw-deliver-runs" / "alpha" / "status.json"
    out.parent.mkdir(parents=True)
    invalid_env_root = tmp_git_repo.parent / "not-a-git-repo"
    invalid_env_root.mkdir()
    env = os.environ.copy()
    env["SW_REPO_ROOT"] = str(invalid_env_root)
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
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert json.loads(out.read_text(encoding="utf-8"))["head"] == head
    assert not (invalid_env_root / ".cursor").exists()


def test_no_consumer_git_repo_fails_closed(tmp_path: Path, repo_root: Path) -> None:
    ship_status = repo_root / "scripts" / "ship-phase-status.py"
    cwd = tmp_path / "cwd"
    configured = tmp_path / "configured"
    cwd.mkdir()
    configured.mkdir()
    out = cwd / "status.json"
    env = os.environ.copy()
    env["SW_REPO_ROOT"] = str(configured)

    proc = subprocess.run(
        [
            sys.executable,
            str(ship_status),
            "--verdict",
            "blocked",
            "--phase",
            "alpha",
            "--cause",
            "test",
            "--out",
            str(out),
        ],
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 2
    assert "consumer-repo:not-found" in proc.stderr
    assert not out.exists()
    assert not (configured / ".cursor").exists()


def test_merge_ready_uses_consumer_root_for_gate_evidence(
    tmp_git_repo: Path, repo_root: Path
) -> None:
    ship_status = repo_root / "scripts" / "ship-phase-status.py"
    phase = "external-runtime-consumer-root"
    head = subprocess.run(
        ["git", "-C", str(tmp_git_repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    run_dir = tmp_git_repo / ".shipwright" / "deliver-runs" / phase
    run_dir.mkdir(parents=True)
    steps = {
        "phase": phase,
        "currentStep": SHIP_CHAIN[-1],
        "lastCompletedStep": SHIP_CHAIN[-1],
        "stepAttempts": {},
        "chain": SHIP_CHAIN,
        "chainSource": "test-fixture",
    }
    steps_path = run_dir / "ship-steps.json"
    steps_path.write_text(json.dumps(steps), encoding="utf-8")
    out = run_dir / "status.json"
    env = os.environ.copy()
    env.update(
        {
            "SHIPWRIGHT_SCRIPTS": str(repo_root / "scripts"),
            "SW_HARNESS": "1",
            "SW_REPO_ROOT": str(tmp_git_repo),
            "SW_RUN_DIR": str(run_dir),
            "SHIP_STEPS_PATH": str(steps_path),
        }
    )

    proc = subprocess.run(
        [
            sys.executable,
            str(ship_status),
            "--verdict",
            "merge-ready-green",
            "--phase",
            phase,
            "--head",
            head,
            "--out",
            str(out),
        ],
        cwd=str(tmp_git_repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert json.loads(out.read_text(encoding="utf-8"))["head"] == head
    evidence_dir = run_dir / "gate-evidence"
    assert evidence_dir.is_dir()
    assert len(list(evidence_dir.glob("*.json"))) == 8
