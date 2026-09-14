#!/usr/bin/env python3
"""Pre-commit guard: reject mutations to complete planning units (PRD 032 R9/R12)."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

def main() -> int:
    repo = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    hook_dir = Path(__file__).resolve().parent
    guard = hook_dir.parent / "scripts" / "authoring_guard.py"
    if not guard.is_file():
        guard = repo / "scripts" / "authoring_guard.py"
    if not guard.is_file():
        print("sw-completed-unit: authoring_guard.py missing; refusing commit", file=sys.stderr)
        return 1
    staged = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=repo, capture_output=True, text=True).stdout.splitlines()
    if not staged:
        return 0
    return subprocess.run([sys.executable, str(guard), str(repo), "check-staged"], cwd=repo).returncode

if __name__ == "__main__":
    raise SystemExit(main())
