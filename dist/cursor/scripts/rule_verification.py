#!/usr/bin/env python3
"""CLI: adversarial rule verification (PRD 064 R7)."""
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rule adversarial verification")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    verifier_brief = sub.add_parser("verifier-brief", help="Build verifier brief")
    verifier_brief.add_argument("--rule", required=True)
    verifier_brief.add_argument("--evidence")
    verifier_brief.add_argument("--run-id")

    skeptic_brief = sub.add_parser("skeptic-brief", help="Build skeptic brief")
    skeptic_brief.add_argument("--rule", required=True)
    skeptic_brief.add_argument("--verifier-result", required=True)
    skeptic_brief.add_argument("--evidence")
    skeptic_brief.add_argument("--run-id")

    evaluate = sub.add_parser("evaluate", help="Evaluate verifier + skeptic pair")
    evaluate.add_argument("--verifier-result", required=True)
    evaluate.add_argument("--skeptic-result", required=True)
    evaluate.add_argument("--out")

    args = parser.parse_args(argv)

    if args.command == "verifier-brief":
        emit(lib.build_verifier_brief(_load_json(args.rule), evidence=_load_json(args.evidence) if args.evidence else {}, run_id=args.run_id))
    if args.command == "skeptic-brief":
        emit(lib.build_skeptic_brief(_load_json(args.rule), lib.normalize_verifier_result(_load_json(args.verifier_result)), evidence=_load_json(args.evidence) if args.evidence else {}, run_id=args.run_id))
    if args.command == "evaluate":
        result = lib.evaluate_verification(lib.normalize_verifier_result(_load_json(args.verifier_result)), lib.normalize_skeptic_result(_load_json(args.skeptic_result)))
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        emit(result, 0 if result.get("promotionReady") else 10)
    return 0


if __name__ == "__main__":
    from _sw.cli import run_module_main
    run_module_main(main)
