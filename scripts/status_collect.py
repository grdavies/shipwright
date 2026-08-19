#!/usr/bin/env python3
"""Operator status collectors for /sw-status (PRD 280 R20)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from decision_graph.frontier import frontier_for_unit  # noqa: E402
from decision_graph.human_action import is_human_action_node  # noqa: E402
from decision_graph.journal import (  # noqa: E402
    DecisionRunJournal,
    load_receipts_for_unit,
    receipts_by_node_from_journal,
)
from decision_graph.receipt import receipt_blocks_node  # noqa: E402


def _node_index(graph: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    spec = graph.get("spec")
    if not isinstance(spec, Mapping):
        return {}
    nodes = spec.get("nodes")
    if not isinstance(nodes, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if isinstance(node, Mapping) and isinstance(node.get("id"), str):
            indexed[node["id"]] = dict(node)
    return indexed


def _blocked_human_action_nodes(
    graph: Mapping[str, Any],
    receipts_by_node: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    nodes = _node_index(graph)
    blocked: list[dict[str, Any]] = []
    for node_id, node in sorted(nodes.items()):
        if not is_human_action_node(node):
            continue
        if str(node.get("status") or "") != "open":
            continue
        if receipt_blocks_node(node, receipts_by_node):
            blocked.append(
                {
                    "nodeId": node_id,
                    "title": str(node.get("title") or ""),
                    "reason": "receipt-required",
                }
            )
    return blocked


def collect_decision_frontier_summary(
    root: Path,
    unit_id: str,
    *,
    run_id: str | None = None,
    graph_path: Path | None = None,
) -> dict[str, Any]:
    """Return ready count and blocked human-action nodes for a planning unit."""
    frontier = frontier_for_unit(root, unit_id, graph_path=graph_path)
    if frontier.get("verdict") != "pass":
        return {
            "verdict": "fail",
            "unitId": unit_id,
            "error": frontier.get("error") or "frontier:failed",
            "readyCount": 0,
            "blockedHumanActions": [],
            "frontier": frontier,
        }

    graph_path_resolved = frontier.get("graphPath")
    graph_document: dict[str, Any] = {}
    if graph_path_resolved:
        try:
            graph_document = json.loads(Path(str(graph_path_resolved)).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            graph_document = {}

    if run_id:
        receipts = receipts_by_node_from_journal(DecisionRunJournal(root, run_id))
    else:
        receipts = load_receipts_for_unit(root, unit_id)

    ready = list(frontier.get("ready") or [])
    blocked_human = _blocked_human_action_nodes(graph_document, receipts)
    blocked_ids = {item["nodeId"] for item in blocked_human}
    admissible_ready = [node_id for node_id in ready if node_id not in blocked_ids]

    return {
        "verdict": "pass",
        "unitId": unit_id,
        "runId": run_id,
        "graphPath": graph_path_resolved,
        "readyCount": len(admissible_ready),
        "ready": admissible_ready,
        "blockedHumanActions": blocked_human,
        "blockedHumanActionCount": len(blocked_human),
        "frontier": {
            "ready": admissible_ready,
            "blocked": frontier.get("blocked") or [],
            "readyCount": len(admissible_ready),
        },
    }


def cmd_decision_frontier(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else Path.cwd()
    unit_id = args.unit_id
    if not unit_id:
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "error": "usage: status_collect.py decision-frontier --unit-id <id>",
                }
            )
        )
        return 2
    graph_path = Path(args.graph) if args.graph else None
    payload = collect_decision_frontier_summary(
        root,
        unit_id,
        run_id=args.run_id,
        graph_path=graph_path,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("verdict") == "pass" else 20


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Operator status collectors for /sw-status")
    parser.add_argument("--root", default="", help="Repository root (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)

    frontier = sub.add_parser("decision-frontier", help="DecisionGraph frontier summary for a unit")
    frontier.add_argument("--unit-id", required=True)
    frontier.add_argument("--run-id", default="")
    frontier.add_argument("--graph", default="")
    frontier.set_defaults(func=cmd_decision_frontier)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
