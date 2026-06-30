#!/usr/bin/env python3
"""Resolve host API token from configured env-var name (PRD 026 R8)."""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

from _sw.cli import build_parser, run_module_main


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(prog="host_token", description="Host token presence/degraded verdict JSON.")
    parser.add_argument("--root", default=None)
    args, _ = parser.parse_known_args(argv)
    root = Path(args.root or Path(__file__).resolve().parent.parent)
    proc = subprocess.run(
        [sys.executable, str(root / "scripts/host_lib.py"), "--root", str(root), "token-status"],
        shell=False,
    )
    return proc.returncode


if __name__ == "__main__":
    run_module_main(main)
