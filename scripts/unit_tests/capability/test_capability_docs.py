"""CI fixtures for capability docs regen + semantic check (PRD 270 R8 phase 10)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_capability_docs_regen_check(repo_root: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/capability_docs.py", "regen-check"],
        cwd=repo_root,
        check=False,
    )
    assert completed.returncode == 0


def test_capability_docs_semantic_check(repo_root: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/capability_docs.py", "check"],
        cwd=repo_root,
        check=False,
    )
    assert completed.returncode == 0
