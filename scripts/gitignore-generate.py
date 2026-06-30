#!/usr/bin/env python3
"""Visibility-driven .gitignore generator (PRD 034 R13)."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import gitignore_generate
from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    root = SCRIPT_DIR.parent
    forwarded: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--repo-root" and i + 1 < len(args):
            root = Path(args[i + 1]).resolve()
            i += 2
        else:
            forwarded.append(args[i])
            i += 1
    return int(gitignore_generate.main(["--root", str(root), *forwarded]))


if __name__ == "__main__":
    run_module_main(main)
