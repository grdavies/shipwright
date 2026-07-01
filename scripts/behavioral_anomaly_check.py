#!/usr/bin/env python3
"""CLI: behavioral-anomaly guardrails (PRD 041 R28)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import behavioral_anomaly_check_lib as lib


def emit(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Behavioral-anomaly guardrails")
    parser.add_argument("--root", default=".")
    parser.add_argument("--tasks")
    parser.add_argument("--verify-status")
    parser.add_argument("--ship-steps")
    parser.add_argument("--baseline", default=".shipwright/pre-agent-diff-baseline.json")
    parser.add_argument("--rollback-marker")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--out")
    parser.add_argument("--no-record", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    result = lib.check(
        root,
        tasks_path=Path(args.tasks) if args.tasks else None,
        verify_status_path=Path(args.verify_status) if args.verify_status else None,
        ship_steps_path=Path(args.ship_steps) if args.ship_steps else None,
        baseline_path=Path(args.baseline) if args.baseline else None,
        rollback_marker_path=Path(args.rollback_marker) if args.rollback_marker else None,
        run_id=args.run_id,
        record_signatures=not args.no_record,
    )
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    code = 20 if result.get("verdict") == "blocking" else (10 if result.get("anomalies") else 0)
    emit(result, code)


if __name__ == "__main__":
    from _sw.cli import run_module_main
    run_module_main(main)
