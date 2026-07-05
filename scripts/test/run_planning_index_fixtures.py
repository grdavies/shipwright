#!/usr/bin/env python3
"""Planning INDEX fixture runner (PRD 046 R101–R103 / gap-020)."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
cmd = [sys.executable, str(ROOT / "scripts/test/run_pytest.py"), "scripts/unit_tests/git", "-q", "-k", "planning_index"]
raise SystemExit(subprocess.run(cmd, cwd=str(ROOT)).returncode)

if __name__ == "__main__":
    raise SystemExit(main() if False else subprocess.run(
        [sys.executable, str(ROOT / "scripts/test/run_pytest.py"), "scripts/unit_tests/git/test_planning_index.py", "-q"],
        cwd=str(ROOT),
    ).returncode)
