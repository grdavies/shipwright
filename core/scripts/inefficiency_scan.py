#!/usr/bin/env python3
"""CLI: inefficiency scanner (PRD 041 R25/R26)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import inefficiency_scan_lib as lib


def emit(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inefficiency scanner")
    parser.add_argument("--root", default=".")
    parser.add_argument("--junit")
    parser.add_argument("--gate-json")
    parser.add_argument("--ci-timing")
    parser.add_argument("--deliver-state")
    parser.add_argument("--tasks")
    parser.add_argument("--run-log")
    parser.add_argument("--verify-status")
    parser.add_argument("--no-draft", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    result = lib.scan(
        root,
        junit_path=Path(args.junit) if args.junit else None,
        gate_json_path=Path(args.gate_json) if args.gate_json else None,
        ci_timing_path=Path(args.ci_timing) if args.ci_timing else None,
        deliver_state_path=Path(args.deliver_state) if args.deliver_state else None,
        tasks_path=Path(args.tasks) if args.tasks else None,
        run_log_path=Path(args.run_log) if args.run_log else None,
        verify_status_path=Path(args.verify_status) if args.verify_status else None,
        draft_to_inbox=not args.no_draft,
    )
    emit(result, 0 if result.get("verdict") in ("ok", "skipped") else 20)


if __name__ == "__main__":
    from _sw.cli import run_module_main
    run_module_main(main)
