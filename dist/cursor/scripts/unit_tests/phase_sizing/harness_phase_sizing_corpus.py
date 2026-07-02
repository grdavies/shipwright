#!/usr/bin/env python3
"""PRD 040 Phase 0 — corpus calibration fixture (deterministic baseline)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
for _entry in (str(_TEST_DIR), str(_SCRIPTS_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from _fixture_lib import repo_root

BASELINE = Path("scripts/test/fixtures/phase-sizing/baseline-distribution.json")


def main() -> int:
    root = repo_root(__file__)
    env = {"PYTHONPATH": str(root / "scripts"), **dict(__import__("os").environ)}
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "phase_sizing_corpus.py"), "--root", str(root), "audit"],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        return proc.returncode
    baseline = root / BASELINE
    if not baseline.is_file():
        print(f"FAIL missing {BASELINE}")
        return 1
    data = json.loads(baseline.read_text(encoding="utf-8"))
    summary = data.get("summary") or {}
    dist = summary.get("distributions") or {}
    if int(summary.get("taskListCount") or 0) < 10:
        print("FAIL taskListCount too small")
        return 1
    if int(summary.get("phaseSampleCount") or 0) < 50:
        print("FAIL phaseSampleCount too small")
        return 1
    defaults = data.get("defaults") or {}
    if "tasks.sizing.thresholds" not in defaults:
        print("FAIL missing sizing thresholds in defaults")
        return 1
    files = dist.get("filesTouched") or {}
    if int(files.get("max") or 0) < int(files.get("min") or 0):
        print("FAIL invalid filesTouched distribution")
        return 1
    print("OK  phase-sizing-corpus-audit")
    print("OK  baseline-distribution-present")
    print("OK  sizing-defaults-derived")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
