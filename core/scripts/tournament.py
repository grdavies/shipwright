#!/usr/bin/env python3
"""CLI: bounded tournament primitive (PRD 064 R5/R6)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import tournament_lib as lib


def emit(obj: dict, code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def _load_json(path: str | None) -> dict:
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _load_json_list(path: str | None) -> list:
    if not path:
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Tournament driver")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("config", help="Resolve tournament config")
    gate = sub.add_parser("should-run", help="Evaluate divergence gate")
    gate.add_argument("--divergence", required=True)
    plan_p = sub.add_parser("plan", help="Plan isolated attempts")
    plan_p.add_argument("--divergence", required=True)
    brief = sub.add_parser("attempt-brief", help="Build attempt brief JSON")
    brief.add_argument("--plan", required=True)
    brief.add_argument("--attempt-id", required=True)
    brief.add_argument("--run-id")
    bracket_p = sub.add_parser("bracket", help="Build deterministic bracket")
    bracket_p.add_argument("--plan", required=True)
    judge_brief = sub.add_parser("judge-brief", help="Build pairwise judge brief")
    judge_brief.add_argument("--match", required=True)
    judge_brief.add_argument("--attempts", required=True)
    judge_brief.add_argument("--plan")
    judge_brief.add_argument("--run-id")
    evaluate = sub.add_parser("evaluate-match", help="Evaluate one judge result")
    evaluate.add_argument("--match", required=True)
    evaluate.add_argument("--judge-result", required=True)
    advance = sub.add_parser("advance", help="Advance bracket after match results")
    advance.add_argument("--bracket", required=True)
    advance.add_argument("--results", required=True)
    persist = sub.add_parser("persist", help="Persist winner + rationale")
    persist.add_argument("--plan", required=True)
    persist.add_argument("--bracket", required=True)
    persist.add_argument("--winner-id", required=True)
    persist.add_argument("--rationale", required=True)
    persist.add_argument("--attempts", required=True)
    persist.add_argument("--out", required=True)

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    cfg = lib.load_workflow_config(root)
    tournament_cfg = lib.resolve_tournament_config(cfg)

    if args.command == "config":
        emit({"tournament": tournament_cfg})
    if args.command == "should-run":
        emit(lib.should_run_tournament(_load_json(args.divergence), tournament_cfg))
    if args.command == "plan":
        emit(lib.plan_attempts(_load_json(args.divergence), tournament_cfg))
    if args.command == "attempt-brief":
        plan = _load_json(args.plan)
        match = next((a for a in (plan.get("attempts") or []) if a.get("id") == args.attempt_id), None)
        if not match:
            emit({"verdict": "fail", "error": f"unknown attempt {args.attempt_id}"}, 20)
        emit(lib.build_attempt_brief(match, divergence=plan, run_id=args.run_id))
    if args.command == "bracket":
        emit(lib.build_bracket(_load_json(args.plan)))
    if args.command == "judge-brief":
        match = _load_json(args.match)
        attempts = _load_json_list(args.attempts)
        lookup = lib.attempt_lookup(attempts)
        rubric = _load_json(args.plan).get("rubric") if args.plan else None
        emit(lib.build_judge_brief(
            match,
            attempt_a=lookup.get(str(match.get("a"))) or {"id": match.get("a")},
            attempt_b=lookup.get(str(match.get("b"))) if match.get("b") else None,
            rubric=rubric if isinstance(rubric, list) else None,
            run_id=args.run_id,
        ))
    if args.command == "evaluate-match":
        emit(lib.evaluate_match(_load_json(args.match), lib.normalize_judge_result(_load_json(args.judge_result))))
    if args.command == "advance":
        emit(lib.advance_bracket(_load_json(args.bracket), _load_json_list(args.results)))
    if args.command == "persist":
        plan = _load_json(args.plan)
        bracket = _load_json(args.bracket)
        attempts = _load_json_list(args.attempts)
        payload = lib.persist_result(
            Path(args.out), plan=plan, bracket=bracket,
            winner=lib.champion_from_attempts(attempts, args.winner_id),
            rationale=args.rationale,
        )
        emit(payload)
    return 0


if __name__ == "__main__":
    from _sw.cli import run_module_main
    run_module_main(main)
