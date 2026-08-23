#!/usr/bin/env python3
"""Kernel guard: refuse mutating dispatch when blocking DecisionGraph nodes are active (PRD 280 R8)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from decision_graph.evidence import check_evidence_required
from decision_graph.schema import NodeKind, load_graph

BLOCKING_KINDS: frozenset[str] = frozenset(
    {
        NodeKind.DECISION.value,
        NodeKind.RESEARCH.value,
        NodeKind.HUMAN_ACTION.value,
    }
)

CAUSE_ACTIVE_BLOCKS_WRITE = "decision-graph:active-nodes-block-production-write"


def active_blocking_nodes(document: dict[str, Any]) -> list[dict[str, Any]]:
    spec = document.get("spec") if isinstance(document.get("spec"), dict) else {}
    nodes = spec.get("nodes") if isinstance(spec.get("nodes"), list) else []
    active: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("kind") not in BLOCKING_KINDS:
            continue
        if node.get("status") != "open":
            continue
        active.append(node)
    return active


def check_mutating_dispatch(
    document: dict[str, Any],
    *,
    write_paths: list[str] | None = None,
    mutating: bool = True,
) -> dict[str, Any]:
    """Refuse production mutating dispatch when blocking nodes remain open."""
    active = active_blocking_nodes(document)
    if not active:
        return {"verdict": "pass", "activeCount": 0}
    if not mutating:
        return {"verdict": "pass", "activeCount": len(active), "note": "read-only dispatch allowed"}
    paths = [str(p).strip() for p in (write_paths or []) if str(p).strip()]
    if not paths:
        return {
            "verdict": "fail",
            "cause": CAUSE_ACTIVE_BLOCKS_WRITE,
            "activeCount": len(active),
            "activeNodeIds": [str(n.get("id") or "") for n in active],
            "note": "mutating dispatch requires explicit write paths",
        }
    return {
        "verdict": "fail",
        "cause": CAUSE_ACTIVE_BLOCKS_WRITE,
        "activeCount": len(active),
        "activeNodeIds": [str(n.get("id") or "") for n in active],
        "writePaths": paths,
    }


def check_production_write(document: dict[str, Any], write_paths: list[str]) -> dict[str, Any]:
    return check_mutating_dispatch(document, write_paths=write_paths, mutating=True)


def emit(payload: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="DecisionGraph mutating-dispatch guard")
    parser.add_argument("--graph", required=True, help="Path to DecisionGraph JSON")
    parser.add_argument(
        "--write-path",
        action="append",
        default=[],
        help="Production write path (repeatable)",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Treat dispatch as read-only (no production write refusal)",
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
    args = parser.parse_args(argv)

    graph_path = Path(args.graph)
    try:
        document = load_graph(graph_path)
    except ValueError as exc:
        emit({"verdict": "fail", "cause": "graph:invalid-json", "message": str(exc)}, 20)

    if args.require_evidence:
        repo_root = Path(args.root) if args.root else SCRIPT_DIR.parent
        evidence_result = check_evidence_required(document, repo_root)
        if evidence_result.get("verdict") != "pass":
            emit(evidence_result, 20)

    result = check_mutating_dispatch(
        document,
        write_paths=list(args.write_path or []),
        mutating=not args.read_only,
    )
    code = 0 if result.get("verdict") == "pass" else 20
    emit(result, code)


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
