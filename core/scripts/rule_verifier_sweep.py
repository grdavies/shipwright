#!/usr/bin/env python3
"""CLI: opt-in per-rule verifier sweep (PRD 064 R8)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import rule_verification_lib as lib


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
    if isinstance(data, dict) and isinstance(data.get("rules"), list):
        return data["rules"]
    return data if isinstance(data, list) else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Per-rule verifier sweep")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("config", help="Resolve sweep config")
    plan = sub.add_parser("plan", help="Plan one verifier per rule")
    plan.add_argument("--rules", required=True)
    brief = sub.add_parser("verifier-brief", help="Build repeat-violation verifier brief")
    brief.add_argument("--rule", required=True)
    brief.add_argument("--evidence")
    brief.add_argument("--run-id")
    synth = sub.add_parser("synthesize", help="Synthesize sweep results")
    synth.add_argument("--results", required=True)
    synth.add_argument("--out")

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    sweep_cfg = lib.resolve_sweep_config(lib.load_workflow_config(root))

    if args.command == "config":
        emit({"ruleVerifierSweep": sweep_cfg})
    if args.command == "plan":
        if not sweep_cfg.get("enabled"):
            emit({"verdict": "skip", "reason": "disabled-default", "jobCount": 0, "jobs": []})
        emit(lib.plan_rule_sweep(_load_json_list(args.rules)))
    if args.command == "verifier-brief":
        brief_obj = lib.build_verifier_brief(_load_json(args.rule), evidence=_load_json(args.evidence) if args.evidence else {}, run_id=args.run_id)
        brief_obj["role"] = "repeat-violation-verifier"
        brief_obj["instructions"] = (
            "Check whether this guardrail rule is repeatedly violated in the supplied diff/transcript evidence. "
            'Return JSON: {"ruleId":"...","verdict":"compliant|violation|inconclusive",'
            '"repeatViolation":bool,"rationale":"...","evidence":[]}'
        )
        emit(brief_obj)
    if args.command == "synthesize":
        normalized = [lib.evaluate_repeat_violation({"id": raw.get("ruleId")}, lib.normalize_verifier_result(raw)) for raw in _load_json_list(args.results) if isinstance(raw, dict)]
        result = lib.synthesize_sweep(normalized)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        emit(result, 20 if result.get("verdict") == "halt" else 0)
    return 0


if __name__ == "__main__":
    from _sw.cli import run_module_main
    run_module_main(main)
