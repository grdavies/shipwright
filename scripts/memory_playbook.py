#!/usr/bin/env python3
"""CLI for confidence-scored playbook memory (PRD 064 R26-R28, R33)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
import memory_playbook_lib as lib


def emit(obj: dict, code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Playbook memory confidence + primary injection")
    parser.add_argument("--root", default=".")
    parser.add_argument("--store")
    sub = parser.add_subparsers(dest="command", required=True)

    match_p = sub.add_parser("match", help="Keyword-match playbooks for signal context")
    match_p.add_argument("--signals-json", required=True)

    inject_p = sub.add_parser("primary-inject", help="Emit primary dispatch context blocks")
    inject_p.add_argument("--signals-json", required=True)

    usage_p = sub.add_parser("record-usage", help="Increment usage counters")
    usage_p.add_argument("--id", required=True)
    usage_p.add_argument("--success", action="store_true")

    promote_p = sub.add_parser("evaluate-promotion", help="Gate draft→active promotion")
    promote_p.add_argument("--id", required=True)
    promote_p.add_argument("--promote", action="store_true")

    sub.add_parser("reconcile-confidence", help="Auto promote/demote confidence fields")

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    store = Path(args.store).resolve() if args.store else lib.resolve_store_dir(root)

    if args.command == "match":
        signals = json.loads(args.signals_json)
        emit({"matches": lib.match_playbooks(store, signal_context=signals, root=root)})

    if args.command == "primary-inject":
        signals = json.loads(args.signals_json)
        emit({"blocks": lib.primary_inject_blocks(store, signal_context=signals, root=root)})

    if args.command == "record-usage":
        emit(lib.record_usage(store, args.id, success=bool(args.success), root=root))

    if args.command == "evaluate-promotion":
        result = lib.evaluate_promotion(store, args.id, root=root, promote=bool(args.promote))
        code = 0 if result.get("verdict") == "ok" else 20
        emit(result, code)

    if args.command == "reconcile-confidence":
        emit(lib.reconcile_store_confidence(store, root=root))

    return 0


if __name__ == "__main__":
    run_module_main(main)
