#!/usr/bin/env python3
"""Ported fixture suite — PRD 062 R20 release completeness meta gate."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
for _entry in (str(_TEST_DIR), str(_SCRIPTS_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from _sw.vendor_paths import repo_root
from unit_tests._harness_runtime import harness_subprocess_env as _harness_env


def main() -> int:
    root = repo_root(__file__)
    env = _harness_env(root)
    test_file = SCRIPT_DIR / "test_prd062_release_completeness.py"
    completed = subprocess.run(
        [sys.executable, str(_SCRIPTS_ROOT / "test" / "run_pytest.py"), str(test_file), "-q"],
        cwd=str(root),
        env=env,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
