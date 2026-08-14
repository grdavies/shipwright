#!/usr/bin/env python3
"""Git pre-push hook — materialize guard + secret scan (PRD 042 R3)."""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path

def main() -> int:
    repo = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    scripts = repo / "scripts"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{scripts}{os.pathsep}{env.get('PYTHONPATH', '')}"
    materialize = scripts / "planning_materialize.py"
    if materialize.is_file():
        proc = subprocess.run([sys.executable, str(materialize), "--root", str(repo), "guard-staged", "--push"], cwd=repo, env=env)
        if proc.returncode != 0:
            return proc.returncode
    scan = scripts / "secret-scan.py"
    if scan.is_file():
        proc = subprocess.run([sys.executable, str(scan), "pre-push"], cwd=repo)
        if proc.returncode != 0:
            return proc.returncode
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
