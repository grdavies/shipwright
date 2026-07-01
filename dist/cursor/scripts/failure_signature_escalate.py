#!/usr/bin/env python3
"""CLI: threshold escalation to root-cause records (PRD 041 R23)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import failure_signature_escalate_lib as lib
import sw_state_write_lib as writer


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def fail(error: str, code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, code)


def load_cfg(root: Path) -> dict[str, Any]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("--failure-text", default="")
    scan.add_argument("--prd-a-flag", action="append", default=[])
    waive = sub.add_parser("ack-flake-waiver")
    waive.add_argument("--record-id", required=True)
    waive.add_argument("--by", default="human")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        if args.command == "scan":
            cfg = load_cfg(root)
            records = lib.scan_and_escalate(
                root,
                cfg,
                failure_text=args.failure_text,
                prd_a_flags=args.prd_a_flag,
            )
            emit({"verdict": "ok", "action": "failure-signature-escalate", "escalated": records})
        record = lib.acknowledge_flake_waiver(root, args.record_id, acknowledged_by=args.by)
        emit({"verdict": "ok", "action": "ack-flake-waiver", "record": record})
    except writer.StateWriteError as exc:
        fail(str(exc), halt=exc.halt)
    return 0


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
