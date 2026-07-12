#!/usr/bin/env python3
"""CLI for execution telemetry capture and retro advisory suggestions (PRD 064 R29/R30)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
import execution_telemetry_lib as lib


def emit(obj: dict, code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execution telemetry capture (R29) and retro advisory (R30)")
    parser.add_argument("--root", default=".")
    parser.add_argument("--phase-slug", default=None)
    parser.add_argument("--run-dir", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("config", help="Resolve executionTelemetry config")

    record = sub.add_parser("record", help="Record one execute/stabilize pass")
    record.add_argument("--command", required=True, choices=sorted(lib.PASS_COMMANDS))
    record.add_argument("--iteration-count", type=int, default=None)
    record.add_argument("--blocker-ledger-size", type=int, default=None)
    record.add_argument("--time-to-green-ms", type=int, default=None)
    record.add_argument("--rca-triggered-count", type=int, default=None)
    record.add_argument("--green", action="store_true")

    sub.add_parser("summary", help="Summarize recorded passes for a phase run dir")

    draft = sub.add_parser("draft-suggestion", help="Draft advisory phase-authoring-improvement suggestion")
    draft.add_argument("--no-persist", action="store_true")

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    run_dir = args.run_dir
    phase_slug = args.phase_slug

    if args.command == "config":
        cfg = lib.load_telemetry_config(root)
        emit(
            {
                "executionTelemetry": {
                    "enabled": cfg.enabled,
                    "suggestionEveryRuns": cfg.suggestion_every_runs,
                }
            }
        )

    if args.command == "record":
        result = lib.record_pass(
            root,
            command=args.command,
            phase_slug=phase_slug,
            run_dir=run_dir,
            iteration_count=args.iteration_count,
            blocker_ledger_size=args.blocker_ledger_size,
            time_to_green_ms=args.time_to_green_ms,
            rca_triggered_count=args.rca_triggered_count,
            green=bool(args.green),
        )
        code = 0 if result.get("verdict") in {"ok", "skipped"} else 20
        emit(result, code)

    if args.command == "summary":
        target = lib.resolve_run_dir(root, phase_slug=phase_slug, run_dir=run_dir)
        passes = lib.load_passes(lib.telemetry_path(target))
        emit({"verdict": "ok", "path": str(lib.telemetry_path(target)), **lib.summarize_passes(passes)})

    if args.command == "draft-suggestion":
        result = lib.draft_authoring_suggestion(
            root,
            phase_slug=phase_slug,
            run_dir=run_dir,
            persist=not args.no_persist,
        )
        code = 0 if result.get("verdict") in {"advisory", "deferred", "no-telemetry", "skipped"} else 20
        emit(result, code)

    return 0


if __name__ == "__main__":
    run_module_main(main)
