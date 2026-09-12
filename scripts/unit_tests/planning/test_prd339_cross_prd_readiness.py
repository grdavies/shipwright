"""PRD 339 R37/R39 cross-PRD readiness milestone (PRD 337 consumer evidence)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from prd339_cross_prd_gate import (
    PRD_339_R37_ACCEPTANCE_TEST,
    PRD_339_R39_ACCEPTANCE_TEST,
    prd339_absorb_acceptance_milestone,
)


def test_cross_prd_milestone_blocked_until_acceptance_tests_exist(tmp_path: Path) -> None:
    """R37/R39 — milestone blocks until list-form absorbs and index self-heal are green."""
    out = prd339_absorb_acceptance_milestone(tmp_path)
    assert out["verdict"] == "blocked"
    assert out["cause"] == "prd-339-r37-r39-not-merged-green"
    blocked_tests = {item["test"] for item in out.get("blocked") or []}
    assert PRD_339_R37_ACCEPTANCE_TEST in blocked_tests
    assert PRD_339_R39_ACCEPTANCE_TEST in blocked_tests


def test_cross_prd_milestone_ready_without_prd337_closeout(repo_root: Path) -> None:
    """R37/R39 — merged-green milestone evidence without implementing PRD 337 closeout."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "scripts")
    proc = subprocess.run(
        [sys.executable, str(repo_root / "scripts/prd339_cross_prd_gate.py"), str(repo_root)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    out = json.loads(proc.stdout)
    assert out.get("verdict") == "ready", out
    assert out.get("requirements") == ["R37", "R39"]
    checks = {item["test"]: item for item in out.get("checks") or []}
    assert checks[PRD_339_R37_ACCEPTANCE_TEST]["verdict"] == "ready"
    assert checks[PRD_339_R39_ACCEPTANCE_TEST]["verdict"] == "ready"
    assert "close-delivery-units" not in str(out.get("resumeCommand") or "")
