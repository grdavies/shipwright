#!/usr/bin/env python3
"""Unified INDEX reconciler — PRD INDEX + planning INDEX (PRD 042 R22)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import build_parser, run_module_main
import reconcile_lib as rl


def emit(obj: dict, exit_code: int = 0) -> int:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(prog="reconcile", description="Unified INDEX reconciler surface.")
    parser.add_argument("command", help="derive|reconcile|planning-reconcile|set-index-status|...")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    ns = parser.parse_args(argv)
    root = rl.git_root()
    cmd = ns.command
    args = list(ns.args)
    if args and args[0] == "--":
        args = args[1:]

    if cmd == "derive":
        data = rl.derive_prd_status(root)
        print(json.dumps(data, indent=2))
        return 0

    if cmd == "reconcile":
        dry_run = "--dry-run" in args
        require_merge = "--require-merge" in args
        allow_default = "--allow-default-branch" in args
        result = rl.reconcile_prd_index(root, dry_run=dry_run, require_merge=require_merge, allow_default=allow_default)
        if result.get("verdict") == "fail":
            print(json.dumps(result), file=sys.stderr)
            return 20
        if dry_run:
            sys.stdout.write(result.get("text", ""))
            return 0
        return emit(result)

    if cmd == "planning-reconcile":
        from planning_reconcile import cmd_reconcile
        cmd_reconcile(root, args)
        return 0

    if cmd == "set-index-status":
        prd = status = ""
        i = 0
        while i < len(args):
            if args[i] == "--prd" and i + 1 < len(args):
                prd = args[i + 1]
                i += 2
            elif args[i] == "--status" and i + 1 < len(args):
                status = args[i + 1]
                i += 2
            else:
                i += 1
        if not prd or not status:
            print("usage: reconcile set-index-status --prd NNN --status <status>", file=sys.stderr)
            return 1
        result = rl.set_index_status(root, prd, status)
        if result.get("verdict") == "fail":
            print(json.dumps(result), file=sys.stderr)
            return 20
        if result.get("verdict") == "partial":
            return emit(result, 21)
        return emit(result)

    if cmd == "append-log-idempotent":
        prd = phase = notes = pr = sha = ""
        i = 0
        while i < len(args):
            if args[i] == "--prd" and i + 1 < len(args):
                prd = args[i + 1]
                i += 2
            elif args[i] == "--phase" and i + 1 < len(args):
                phase = args[i + 1]
                i += 2
            elif args[i] == "--notes" and i + 1 < len(args):
                notes = args[i + 1]
                i += 2
            elif args[i] == "--pr" and i + 1 < len(args):
                pr = args[i + 1]
                i += 2
            elif args[i] == "--sha" and i + 1 < len(args):
                sha = args[i + 1]
                i += 2
            else:
                i += 1
        if not prd or not phase:
            print("--prd and --phase required", file=sys.stderr)
            return 1
        return emit(rl.append_log_idempotent(root, prd=prd, phase=phase, notes=notes, pr=pr, sha=sha))

    if cmd == "deliver-runs":
        from wave_state import enumerate_scoped_runs
        runs = enumerate_scoped_runs(root)
        if "--json" in args:
            return emit({"deliverRuns": runs, "indexPath": str(root / ".cursor/sw-deliver-runs/index.json")})
        for run in runs:
            print(f"{run.get('slug')}: {run.get('target')} verdict={run.get('verdict')} lock={run.get('lockHeld')}")
        return 0

    if cmd == "gap-resolve":
        proc = subprocess.run([sys.executable, str(SCRIPT_DIR / "living-status-gap-resolve.py"), *args], cwd=str(root))
        return proc.returncode

    if cmd in ("cycle-check", "doctor", "relief-check"):
        import planning_graph as pg
        if cmd == "cycle-check":
            pg.main([str(root), "cycle-check", *args])
        elif cmd == "doctor":
            pg.main([str(root), "doctor", *args])
        else:
            pg.main([str(root), "relief-check", *args])
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    run_module_main(main)
