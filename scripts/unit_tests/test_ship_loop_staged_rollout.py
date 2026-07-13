"""Staged-rollout atomicity — enforcement + writers land together (PRD 065 R17)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS = SCRIPT_DIR.parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def test_gate_enforcement_and_writers_coexist(repo_root: Path) -> None:
    required = (
        "scripts/ship_loop.py",
        "scripts/ship_gate_handlers.py",
        "scripts/gate_evidence.py",
        "scripts/merge_ready_enforcement.py",
        "scripts/ship-phase-status.py",
        "core/sw-reference/gate-manifest.json",
    )
    for rel in required:
        assert (repo_root / rel).is_file(), f"missing staged-rollout artifact: {rel}"


def test_ship_phase_status_wires_mandatory_evidence_gate(repo_root: Path) -> None:
    text = (repo_root / "scripts/ship-phase-status.py").read_text(encoding="utf-8")
    assert "evaluate_mandatory_gate_evidence" in text
    assert "gap-check-gate" in text


def test_staged_rollout_no_orphan_enforcement_commit(repo_root: Path) -> None:
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "log",
            "-1",
            "--format=%H",
            "--",
            "scripts/merge_ready_enforcement.py",
            "scripts/ship_gate_handlers.py",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    merge_head = proc.stdout.strip()
    assert merge_head
    for rel in ("scripts/ship_gate_handlers.py", "scripts/gate_evidence.py"):
        show = subprocess.run(
            ["git", "-C", str(repo_root), "cat-file", "-e", f"{merge_head}:{rel}"],
            capture_output=True,
        )
        assert show.returncode == 0, f"{rel} missing at enforcement introduction {merge_head[:8]}"
