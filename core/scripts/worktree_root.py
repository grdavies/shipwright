#!/usr/bin/env python3
"""Worktree root recognition for hook-state alignment (PRD 050 A1 R21)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main


def git_toplevel(start: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ValueError(f"not a git repository: {start}")
    return Path(proc.stdout.strip()).resolve()


def primary_worktree_path(repo_root: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return repo_root.resolve()
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            return Path(line.split(" ", 1)[1].strip()).resolve()
    return repo_root.resolve()


def is_shipwright_worktree(toplevel: Path, primary: Path) -> bool:
    """True for `.sw-worktrees/*` paths and non-primary linked worktrees."""
    toplevel = toplevel.resolve()
    primary = primary.resolve()
    sw_root = primary / ".sw-worktrees"
    if toplevel == sw_root or sw_root in toplevel.parents:
        return True

    proc = subprocess.run(
        ["git", "-C", str(primary), "worktree", "list", "--porcelain"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return False

    first = True
    current_path: Path | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = Path(line.split(" ", 1)[1].strip()).resolve()
            if first:
                first = False
                continue
            if current_path == toplevel:
                return True
    return False


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="worktree_root.py")
    parser.add_argument("--toplevel", required=True)
    parser.add_argument("--primary", required=True)
    ns = parser.parse_args(argv)
    result = is_shipwright_worktree(Path(ns.toplevel), Path(ns.primary))
    print(json.dumps({"recognized": result}))
    return 0


if __name__ == "__main__":
    run_module_main(main)
