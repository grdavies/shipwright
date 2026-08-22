#!/usr/bin/env python3
"""Credential doctor CLI — identity-aware authentication diagnostics (PRD 080 phase 22 / R7).

Default invocation reports per-checklist-step status via ``credentials.doctor.diagnose_repository``
(PRD 324 phase 2): identity source, credentialRef binding, selector allowlists, and resolution probe.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
from credentials.doctor import (
    CREDENTIAL_DOCTOR_CLI,
    diagnose_repository,
    remediate,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="credentials-doctor.py")
    parser.add_argument("--root", default=None, help="Repository root")
    sub = parser.add_subparsers(dest="command")

    remediate_parser = sub.add_parser("remediate", help="Apply remediation for a failure code")
    remediate_parser.add_argument("--scope", required=True, choices=["local", "ci"])
    remediate_parser.add_argument("--code", required=True)
    remediate_parser.add_argument("--root", default=None)

    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if getattr(args, "root", None) else SCRIPT_DIR.parent

    if args.command == "remediate":
        result = remediate(
            scope=args.scope,
            code=args.code,
            root=root,
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("verdict") in {"ok", "noop"} else 1

    report = diagnose_repository(root)
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "ok" else 1


if __name__ == "__main__":
    run_module_main(main)
