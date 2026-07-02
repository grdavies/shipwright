#!/usr/bin/env python3
"""Thin shim — scope fixtures ported to scripts/unit_tests/scope/ (PRD 054 phase 2)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _fixture_lib import repo_root


def main() -> int:
    root = repo_root(__file__)
    return subprocess.call(
        [sys.executable, str(root / "scripts/test/run_pytest.py"), "scripts/unit_tests/scope"],
        cwd=str(root),
    )


if __name__ == "__main__":
    raise SystemExit(main())
