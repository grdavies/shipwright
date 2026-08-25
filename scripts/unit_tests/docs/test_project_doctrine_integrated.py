"""PRD 330 phase 9 — integrated ProjectDoctrine adoption acceptance via fixture runner."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_integrated_project_doctrine_fixtures(repo_root: Path) -> None:
    script = repo_root / "scripts" / "test" / "run_project_doctrine_fixtures.py"
    assert script.is_file(), f"missing integrated fixture runner: {script}"
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("SW_PHASE")
        and k
        not in {
            "SW_RUN_DIR",
            "SW_REPO_ROOT",
            "SW_INTEGRATION_BRANCH",
            "PYTHONHOME",
        }
    }
    env["PYTHONPATH"] = str(repo_root / "scripts")
    env["ROOT"] = str(repo_root)
    env["SW_REPO_ROOT"] = str(repo_root)
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, (
        f"integrated fixtures failed\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
