#!/usr/bin/env python3
"""CLI: record cross-run failure signatures (PRD 041 R22)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import failure_signature_record_lib as lib


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def fail(error: str, code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--check-id", required=True)
    rec.add_argument("--exit-code", type=int, default=20)
    rec.add_argument("--job-id", default="local")
    rec.add_argument("--message", required=True)
    rec.add_argument("--source", default="cli")
    rec.add_argument("--run-id", default="")
    merge = sub.add_parser("index-merge")
    merge.add_argument("--worktree", action="append", default=[])
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "index-merge":
        result = lib.index_merge(root, worktrees=args.worktree)
        emit({"verdict": "ok", "action": "index-merge", **result})
    record = lib.record_from_surface(
        root,
        args.source,
        check_id=args.check_id,
        exit_code=args.exit_code,
        job_id=args.job_id,
        message=args.message,
        run_id=args.run_id,
    )
    emit({"verdict": "ok", "action": "failure-signature-record", "record": record})
    return 0


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
