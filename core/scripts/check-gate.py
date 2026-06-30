#!/usr/bin/env python3
"""Deterministic Shipwright CI readiness gate (PRD 042 phase 3)."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import build_parser, run_module_main
import check_gate_lib as gate


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="check-gate",
        description="Deterministic CI readiness gate — JSON verdict on stdout.",
    )
    parser.add_argument("pr", nargs="?", help="PR number (optional; resolved from branch)")
    args = parser.parse_args(argv)
    root = gate.git_root()
    exit_code, _payload = gate.run_gate(root, args.pr)
    return exit_code


if __name__ == "__main__":
    run_module_main(main)
