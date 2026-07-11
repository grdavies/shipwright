#!/usr/bin/env python3
"""CLI: adversarial completion-claims audit (PRD 064 R3/R4)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import claims_audit_lib as lib


def emit(obj: dict, code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Completion-claims audit")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Audit completed claims for a phase")
    run_p.add_argument("--tasks", required=True)
    run_p.add_argument("--phase-id", required=True)
    run_p.add_argument("--diff-base")
    run_p.add_argument("--head")
    run_p.add_argument("--agent-result")
    run_p.add_argument("--out")

    brief_p = sub.add_parser("brief", help="Emit agent brief JSON")
    brief_p.add_argument("--tasks", required=True)
    brief_p.add_argument("--phase-id", required=True)
    brief_p.add_argument("--diff-base")

    collect_p = sub.add_parser("collect", help="Re-audit status.json completionClaims at deliver collect")
    collect_p.add_argument("--status", required=True)
    collect_p.add_argument("--tasks", required=True)
    collect_p.add_argument("--phase-id", required=True)
    collect_p.add_argument("--phase-branch")

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    if args.command == "brief":
        tasks_path = Path(args.tasks)
        text = tasks_path.read_text(encoding="utf-8")
        claims = lib.completed_claims(text, args.phase_id)
        base = args.diff_base or lib.resolve_diff_base(root)
        touched = lib.git_diff_paths(root, base)
        emit(lib.build_agent_brief(claims, diff_paths=touched))

    if args.command == "run":
        agent_claims = None
        if args.agent_result:
            raw = json.loads(Path(args.agent_result).read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                agent_claims = lib.normalize_agent_claims(raw.get("claims"))
            else:
                agent_claims = lib.normalize_agent_claims(raw)
        result = lib.audit_phase_claims(
            root,
            tasks_path=Path(args.tasks),
            phase_id=args.phase_id,
            agent_claims=agent_claims,
            diff_base=args.diff_base,
            head=args.head,
        )
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        code = 20 if result.get("verdict") == "fail" else 0
        emit(result, code)

    if args.command == "collect":
        status = json.loads(Path(args.status).read_text(encoding="utf-8"))
        result = lib.collect_audit_from_status(
            root,
            status,
            tasks_path=Path(args.tasks),
            phase_id=args.phase_id,
            phase_branch=args.phase_branch,
        )
        code = 20 if result.get("verdict") == "fail" else 0
        emit(result, code)

    return 0


if __name__ == "__main__":
    from _sw.cli import run_module_main
    run_module_main(main)
