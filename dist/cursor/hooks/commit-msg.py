#!/usr/bin/env python3
"""Git commit-msg hook — Conventional Commits validator (PRD 042 R3)."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

def main() -> int:
    if len(sys.argv) < 2:
        print("commit-msg: message file required", file=sys.stderr)
        return 2
    repo = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    guard = repo / "scripts" / "commit-msg-guard.py"
    if not guard.is_file():
        print("commit-msg: commit-msg-guard.py missing", file=sys.stderr)
        return 1
    return subprocess.run([sys.executable, str(guard), "validate", sys.argv[1]], cwd=repo).returncode

if __name__ == "__main__":
    raise SystemExit(main())
