"""PRD 342 R34 — Acceptance Scenarios + Success Criteria with grandfathering."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(repo: Path, fixture: str) -> tuple[int, dict]:
    path = repo / "scripts/test/fixtures/spec-rigor" / fixture
    proc = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts/spec-rigor-check.py"),
            "--artifact",
            "prd",
            "--path",
            str(path),
            "--tier",
            "standard",
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {"verdict": "fail", "raw": proc.stdout, "stderr": proc.stderr}
    return proc.returncode, data


def test_grandfathered_prd_without_v2_sections_passes(repo_root: Path) -> None:
    code, data = _run(repo_root, "prd-pass.md")
    assert code == 0
    assert data.get("verdict") == "pass"


def test_v2_prd_with_new_sections_passes(repo_root: Path) -> None:
    code, data = _run(repo_root, "prd-pass-v2.md")
    assert code == 0
    assert data.get("verdict") == "pass"


def test_v2_prd_missing_new_sections_fails(repo_root: Path) -> None:
    code, data = _run(repo_root, "prd-fail-v2-missing-sections.md")
    assert code != 0
    assert data.get("verdict") == "fail"
    messages = " ".join(f.get("message", "") for f in data.get("findings", []))
    assert "Acceptance Scenarios" in messages
    assert "Success Criteria" in messages
