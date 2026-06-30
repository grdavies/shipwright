#!/usr/bin/env python3
"""Fail-closed guard: block implementation entry on bare default-branch checkout (PRD 002 R6/R27)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main


def read_default_branch(root: Path) -> str:
    for candidate in (root / ".cursor/workflow.config.json", root / "workflow.config.json"):
        if candidate.is_file():
            try:
                cfg = json.loads(candidate.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                break
            return str(cfg.get("defaultBaseBranch", "main"))
    return "main"


def main(argv: list[str] | None = None) -> int:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print("sw-assert-worktree: not inside a git repository", file=sys.stderr)
        return 2

    root = Path(proc.stdout.strip())
    default_branch = read_default_branch(root)
    current_proc = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    current = current_proc.stdout.strip()
    if not current:
        print(
            "sw-assert-worktree: detached HEAD — provision a worktree and phase branch first",
            file=sys.stderr,
        )
        return 1

    if current != default_branch:
        return 0

    if current.startswith("hotfix/") or current.startswith("release/"):
        return 0

    git_file = root / ".git"
    if git_file.is_file():
        first_line = git_file.read_text(encoding="utf-8").splitlines()[:1]
        if first_line and first_line[0].startswith("gitdir:"):
            return 0

    print(
        f"sw-assert-worktree: refused — implementation on bare {default_branch} without a linked worktree",
        file=sys.stderr,
    )
    print(
        "sw-assert-worktree: run /sw-worktree provision then /sw-start before /sw-execute",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    run_module_main(main)
