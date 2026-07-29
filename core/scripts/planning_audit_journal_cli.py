#!/usr/bin/env python3
"""PRD 082 phase 9 — authority audit journal CLI (R26)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_audit_journal as paj

VERIFY_EXIT_OK = 0
VERIFY_EXIT_CHAIN_INVALID = 21
VERIFY_EXIT_USAGE = 2


def emit(payload: dict, code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(code)


def cmd_verify(root: Path) -> int:
    result = paj.verify_chain(root)
    if result.get("verdict") == "ok":
        emit(result, VERIFY_EXIT_OK)
    emit(
        {
            **result,
            "blocksAuthorityChanges": True,
            "stableFailureCode": VERIFY_EXIT_CHAIN_INVALID,
        },
        VERIFY_EXIT_CHAIN_INVALID,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Planning authority audit journal CLI (PRD 082 R26)")
    parser.add_argument("--root", type=Path, default=SCRIPT_DIR.parent)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify", help="Verify hash chain integrity; blocks authority changes when invalid")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == "verify":
        return cmd_verify(root)
    emit({"verdict": "fail", "error": "unknown-command"}, VERIFY_EXIT_USAGE)


if __name__ == "__main__":
    main()
