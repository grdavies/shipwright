#!/usr/bin/env python3
"""Fail-closed pre-PR scoped pytest smoke (PRD 063 R4)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
TEST_DIR = SCRIPT_DIR / "test"
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

from _sw.cli import run_module_main


def run_pre_pr_smoke(root: Path, *, scope: str = "phase") -> tuple[int, str | None]:
    from _runner import run_pytest_scope

    os.environ.setdefault("SW_TEST_SCOPE", scope)
    ec = run_pytest_scope(root, scope=scope)
    if ec == 0:
        return 0, None
    return ec, f"pre-pr-smoke:pytest-exit-{ec}"


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    root = Path(args[0]).resolve() if args else Path.cwd().resolve()
    ec, cause = run_pre_pr_smoke(root)
    if ec == 0:
        print(json.dumps({"verdict": "pass", "action": "pre-pr-smoke", "scope": "phase"}))
        return 0
    print(
        json.dumps(
            {
                "verdict": "fail",
                "action": "pre-pr-smoke",
                "halt": "pre-pr-smoke",
                "cause": cause,
                "exitCode": ec,
            }
        ),
        file=sys.stderr,
    )
    return 20


if __name__ == "__main__":
    run_module_main(main)
