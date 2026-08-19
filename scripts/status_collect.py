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

RADAR_LAST_REL = Path(".cursor/sw-architecture-radar/last.json")
VOCAB_DIVERGENCE_LAST_REL = Path(".cursor/sw-vocabulary-divergence/last.json")


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def collect_architecture_radar_last(root: Path) -> dict[str, Any]:
    """Return read-only summary of the latest architecture radar scan artifact."""
    root = root.resolve()
    last_path = root / RADAR_LAST_REL
    payload: dict[str, Any] = {
        "verdict": "pass",
        "readOnly": True,
        "present": False,
        "artifactPath": str(RADAR_LAST_REL.as_posix()),
    }
    last = _read_json_object(last_path)
    if not last:
        return payload

    payload["present"] = True
    payload["scanId"] = last.get("scanId")
    payload["scannedAt"] = last.get("scannedAt")
    payload["scanDir"] = last.get("scanDir")
    payload["candidatesPath"] = last.get("candidatesPath")

    candidates_rel = last.get("candidatesPath")
    if candidates_rel:
        candidates_doc = _read_json_object(root / str(candidates_rel))
        if candidates_doc:
            candidates = candidates_doc.get("candidates")
            if isinstance(candidates, list):
                payload["candidateCount"] = len(candidates)
                payload["topCandidates"] = [
                    {
                        "modulePath": item.get("modulePath"),
                        "strength": item.get("strength"),
                        "disposition": item.get("disposition"),
                    }
                    for item in candidates[:3]
                    if isinstance(item, dict)
                ]
    return payload


def collect_vocabulary_divergence_last(root: Path) -> dict[str, Any]:
    """Return read-only summary of the latest vocabulary divergence artifact."""
    root = root.resolve()
    last_path = root / VOCAB_DIVERGENCE_LAST_REL
    payload: dict[str, Any] = {
        "verdict": "pass",
        "readOnly": True,
        "present": False,
        "artifactPath": str(VOCAB_DIVERGENCE_LAST_REL.as_posix()),
    }
    last = _read_json_object(last_path)
    if not last:
        return payload

    divergences = last.get("divergence")
    divergence_count = len(divergences) if isinstance(divergences, list) else 0
    payload.update(
        {
            "present": True,
            "checkedAt": last.get("checkedAt"),
            "strictMode": bool(last.get("strictMode")),
            "maxSeverity": last.get("maxSeverity"),
            "divergenceCount": divergence_count,
            "registryTermCount": last.get("registryTermCount"),
            "humanGated": last.get("humanGated"),
        }
    )
    return payload


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


def cmd_architecture_radar_last(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else Path.cwd()
    payload = collect_architecture_radar_last(root)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("verdict") == "pass" else 20


def cmd_vocabulary_divergence_last(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else Path.cwd()
    payload = collect_vocabulary_divergence_last(root)
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

    radar_last = sub.add_parser(
        "architecture-radar-last",
        help="Latest architecture radar scan artifact summary (read-only)",
    )
    radar_last.set_defaults(func=cmd_architecture_radar_last)

    vocab_last = sub.add_parser(
        "vocabulary-divergence-last",
        help="Latest vocabulary divergence artifact summary (read-only)",
    )
    vocab_last.set_defaults(func=cmd_vocabulary_divergence_last)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
