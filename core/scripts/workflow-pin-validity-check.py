#!/usr/bin/env python3
"""CLI: validate third-party action pins in GitHub workflow files (PRD 083 R10).

See workflow_pin_validity_check_lib for implementation details.

Exit codes:
  0   — all pins valid (verdict: pass or warn)
  20  — confirmed-invalid pin detected (verdict: fail)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import workflow_pin_validity_check_lib as lib
from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="workflow-pin-validity-check",
        description="Validate third-party action pins in GitHub workflow files (PRD 083 R10).",
    )
    parser.add_argument("--root", default=".", help="Repository root (default: .)")
    parser.add_argument(
        "--token",
        default=None,
        help="GitHub API token (default: GH_TOKEN or GITHUB_TOKEN env var)",
    )
    parser.add_argument(
        "--skip-api",
        action="store_true",
        help="Skip GitHub API validation; consult static allowlist only",
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    root = Path(args.root).resolve()
    token = args.token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    skip_api = args.skip_api

    exit_code, result = lib.run_check(root, token=token, skip_api=skip_api)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    run_module_main(main)
