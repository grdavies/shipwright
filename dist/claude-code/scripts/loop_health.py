#!/usr/bin/env python3
"""CLI: loop-health aggregation (PRD 041 R29)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import loop_health_lib as lib


def emit(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Loop-health downstream-cost metrics")
    parser.add_argument("--root", default=".")
    parser.add_argument("--deliver-state", default=None)
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--summary", action="store_true", help="Emit surface summary only")
    parser.add_argument("--stale-alerts", action="store_true", help="Emit inbox staleness alerts")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    deliver = Path(args.deliver_state) if args.deliver_state else None
    if args.stale_alerts:
        emit({"verdict": "ok", "alerts": lib.stale_inbox_alerts(root)}, 0)
    if args.summary:
        record = lib.build_record(root, deliver_state_path=deliver)
        emit({"verdict": "ok", **lib.surface_summary(record)}, 0)
    result = lib.aggregate(
        root,
        deliver_state_path=deliver,
        persist=not args.no_persist,
    )
    code = 0 if result.get("verdict") in ("ok", "skipped") else 20
    emit(result, code)


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
