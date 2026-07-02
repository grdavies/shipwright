#!/usr/bin/env python3
"""Author-time capability manifest lint — precedence conflicts and anti-spoof (R11, R25, R27)."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    import capability_manifest_lint

    old_argv = sys.argv
    try:
        sys.argv = [old_argv[0], *(argv if argv is not None else old_argv[1:])]
        return capability_manifest_lint.main()
    finally:
        sys.argv = old_argv


if __name__ == "__main__":
    run_module_main(main)
