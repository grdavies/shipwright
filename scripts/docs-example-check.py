#!/usr/bin/env python3
"""CLI wrapper for docs_example_check (PRD 345 R20)."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    import docs_example_check
    from _sw.cli import delegate_argv_main

    return delegate_argv_main(docs_example_check.main, argv, prog="docs-example-check.py")


if __name__ == "__main__":
    run_module_main(main)
