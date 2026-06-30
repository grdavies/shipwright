#!/usr/bin/env python3
"""Git commit-msg hook — Conventional Commits validator (PRD 042 R3)."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

def main() -> int:
    if len(sys.argv) < 2:
        print("commit-msg: message file required", file=sys.stderr)
        return 2
    repo = Path(__file__).resolve().parents[2]
    guard = repo / "scripts" / "commit-msg-guard.sh"
    if not guard.is_file():
        print("commit-msg: commit-msg-guard.sh missing", file=sys.stderr)
        return 1
    return subprocess.run(["bash", str(guard), "validate", sys.argv[1]], cwd=repo).returncode

if __name__ == "__main__":
    raise SystemExit(main())
