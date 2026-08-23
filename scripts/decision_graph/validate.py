#!/usr/bin/env python3
"""CLI: validate DecisionGraph documents (PRD 280 R1/R6)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from decision_graph.evidence import check_evidence_required
from decision_graph.schema import load_graph, validate_graph


def emit(payload: dict[str, object], code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Validate a DecisionGraph JSON document")
    parser.add_argument("--graph", required=True, help="Path to DecisionGraph JSON file")
    parser.add_argument(
        "--no-freeze-check",
        action="store_true",
        help="Skip open-unknown freeze rule (schema + graph structure only)",
    )
    parser.add_argument(
        "--require-evidence",
        action="store_true",
        help="Fail closed when resolved decision nodes with requiresEvidence lack linked records",
    )
    parser.add_argument(
        "--root",
        help="Repository root for evidence store discovery (defaults to plugin root)",
    )
    parser.add_argument("--out", help="Optional path to write JSON result")
    args = parser.parse_args(argv)

    graph_path = Path(args.graph)
    try:
        document = load_graph(graph_path)
    except ValueError as exc:
        emit({"verdict": "fail", "errors": [{"code": "graph:invalid-json", "message": str(exc)}]}, 20)

    result = validate_graph(document, check_freeze=not args.no_freeze_check)
    if result.get("verdict") == "pass" and args.require_evidence:
        repo_root = Path(args.root) if args.root else SCRIPT_DIR.parent.parent
        evidence_result = check_evidence_required(document, repo_root)
        if evidence_result.get("verdict") != "pass":
            result = evidence_result
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    code = 0 if result.get("verdict") == "pass" else 20
    emit(result, code)


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
