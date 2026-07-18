#!/usr/bin/env python3
"""Unified pytest entry for Shipwright test scopes (PRD 054 R17, amendment A1)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# Bootstrap scripts/ on path before _sw imports.
_scripts = SCRIPT_DIR.parent
if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))

from _sw.cli import build_parser, run_module_main
from _sw.vendor_paths import bootstrap_vendor_paths, repo_root as sw_repo_root

REPO_ROOT = sw_repo_root()


def run_pytest(argv: list[str] | None = None, *, root: Path | None = None) -> int:
    resolved = root or sw_repo_root()
    bootstrap_vendor_paths(resolved)
    import pytest

    args = list(argv or [])
    # Manifest-scoped shards pass explicit path args; do not fan out to full unit_tests.
    if not args:
        args = ["scripts/unit_tests"]
    prev = Path.cwd()
    try:
        os.chdir(resolved)
        return int(pytest.main(args))
    finally:
        os.chdir(prev)


def main(cli_argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="run-pytest",
        description="Invoke vendored pytest against scripts/unit_tests (PRD 054).",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to pytest (default: scripts/unit_tests)",
    )
    parser.add_argument("--root", default=str(REPO_ROOT), help="Repository root")
    args = parser.parse_args(cli_argv)
    root = Path(args.root)
    forwarded = args.pytest_args
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    return run_pytest(forwarded or None, root=root)


if __name__ == "__main__":
    run_module_main(main)
