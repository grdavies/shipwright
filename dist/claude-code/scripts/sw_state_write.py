#!/usr/bin/env python3
"""CLI for sole redacting state writer (PRD 041 R31)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import sw_state_write_lib as lib


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def fail(error: str, code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sole redacting writer for sw-* stores")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    write_p = sub.add_parser("write")
    write_p.add_argument("--store", required=True)
    write_p.add_argument("--rel", default=None)
    write_p.add_argument("--file", default=None)
    merge_p = sub.add_parser("index-merge")
    merge_p.add_argument("--store", required=True)
    merge_p.add_argument("--worktree", action="append", default=[])
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if args.command == "write":
            raw = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
            path = lib.write_from_text(root, store=args.store, text=raw, rel=args.rel)
            emit({"verdict": "ok", "action": "write", "store": args.store, "path": str(path)})
        else:
            result = lib.index_merge(root, store=args.store, worktrees=args.worktree)
            emit({"verdict": "ok", "action": "index-merge", **result})
    except lib.StateWriteError as exc:
        fail(str(exc), halt=exc.halt)
    return 0


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
