#!/usr/bin/env python3
"""Mechanical gap resolve on PRD ship (PRD 035 A2 R51)."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main


def git_root() -> Path:
    proc = subprocess.run(["git", "-C", str(Path.cwd()), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else SCRIPT_DIR.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="living-status-gap-resolve.py")
    parser.add_argument("--absorbing-prd", required=True)
    parser.add_argument("--pr", default="")
    args = parser.parse_args(argv)
    root = git_root()
    import gap_backlog
    gap_args = ["--root", str(root), "flip", "--resolve", "--prd", args.absorbing_prd]
    if args.pr:
        gap_args.extend(["--pr", args.pr])
    gap_backlog.main(gap_args)
    return 0


if __name__ == "__main__":
    run_module_main(main)
