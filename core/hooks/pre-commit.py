#!/usr/bin/env python3
"""Git pre-commit hook — fail-closed guards (PRD 042 R3)."""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path

def _run_py(script: Path, cwd: Path) -> int:
    return subprocess.run([sys.executable, str(script)], cwd=cwd).returncode

def _run_sh(script: Path, cwd: Path, *args: str) -> int:
    return subprocess.run(["bash", str(script), *args], cwd=cwd).returncode

def main() -> int:
    hook_dir = Path(__file__).resolve().parent
    repo = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    scripts = repo / "scripts"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{scripts}{os.pathsep}{env.get('PYTHONPATH', '')}"
    for name in ("pre-commit-frozen.py", "pre-commit-completed-unit.py"):
        helper = hook_dir / name
        if helper.is_file() and _run_py(helper, repo) != 0:
            return 1
    for guard, args in ((scripts / "index-region-guard.sh", ("--staged",)), (scripts / "planning-privacy-guard.sh", ("--staged",))):
        if guard.is_file() and _run_sh(guard, repo, *args) != 0:
            return 1
    graph = scripts / "planning_graph.py"
    if graph.is_file():
        proc = subprocess.run([sys.executable, str(graph), str(repo), "cycle-check", "--staged"], cwd=repo, env=env)
        if proc.returncode != 0:
            return proc.returncode
    materialize = scripts / "planning_materialize.py"
    if materialize.is_file():
        proc = subprocess.run([sys.executable, str(materialize), "--root", str(repo), "guard-staged"], cwd=repo, env=env)
        if proc.returncode != 0:
            return proc.returncode
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
