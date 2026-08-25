#!/usr/bin/env python3
"""Provider-backed frontier projection with local text fallback (PRD 331 R22, R43, R44, R45)."""
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from exploration_security import (  # noqa: E402
    ExplorationSecurityError,
    sanitize_projection,
)
from exploration_store import ExplorationStore, utc_now  # noqa: E402
from explore_command_contract import INTERACTION_STATES  # noqa: E402

PROJECTION_VERSION = "ExplorationFrontierProjection@v1"
OPEN_STATUSES = frozenset({"open", "active"})
TERMINAL_STATUSES = frozenset({"resolved", "closed", "superseded", "cancelled"})

ProviderFn = Callable[[Mapping[str, Any]], dict[str, Any]]


class ExplorationProjectionError(ValueError):
    """Invalid exploration projection request."""


def _node_index(map_document: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for node in map_document.get("nodes") or []:
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            indexed[node["id"]] = dict(node)
    return indexed


def _is_prototype_node(node: Mapping[str, Any]) -> bool:
    if node.get("prototype") is True:
        return True
    node_type = str(node.get("type") or "")
    return node_type == "prototype"


def _production_eligible(node: Mapping[str, Any]) -> bool:
    return not _is_prototype_node(node)


def _node_summary(node: Mapping[str, Any], *, superseded: bool) -> dict[str, Any]:
    node_id = str(node.get("id") or "")
    summary: dict[str, Any] = {
        "nodeId": node_id,
        "type": str(node.get("type") or ""),
        "status": str(node.get("status") or ""),
        "title": str(node.get("title") or node.get("statement") or "").strip(),
        "superseded": superseded,
        "productionEligible": _production_eligible(node),
    }
    if node.get("supersedes"):
        summary["supersedes"] = str(node.get("supersedes"))
    return summary


def compute_frontier(map_document: Mapping[str, Any]) -> dict[str, Any]:
    """Derive admissible frontier nodes without mutating canonical state (R22)."""
    nodes = _node_index(map_document)
    superseded_ids = {
        str(node_id)
        for node_id in (map_document.get("supersededNodeIds") or [])
        if isinstance(node_id, str)
    }
    ready: list[str] = []
    blocked: list[str] = []
    summaries: list[dict[str, Any]] = []

    for node_id in sorted(nodes):
        node = nodes[node_id]
        status = str(node.get("status") or "")
        superseded = node_id in superseded_ids or status == "superseded"
        summaries.append(_node_summary(node, superseded=superseded))
        if superseded or status in TERMINAL_STATUSES:
            continue
        if status in OPEN_STATUSES:
            ready.append(node_id)
            continue
        blocked.append(node_id)

    return {
        "ready": ready,
        "blocked": blocked,
        "readyCount": len(ready),
        "nodeSummaries": summaries,
    }


def _projection_base(map_document: Mapping[str, Any]) -> dict[str, Any]:
    map_id = str(map_document.get("id") or "").strip()
    if not map_id:
        raise ExplorationProjectionError("missing-map-id")
    revision = map_document.get("revision")
    if not isinstance(revision, int) or revision < 1:
        raise ExplorationProjectionError("invalid-map-revision")
    frontier = compute_frontier(map_document)
    interaction = map_document.get("interaction")
    interaction_state = None
    if isinstance(interaction, dict):
        raw_state = str(interaction.get("state") or "").strip()
        if raw_state in INTERACTION_STATES:
            interaction_state = raw_state
    return {
        "version": PROJECTION_VERSION,
        "explorationMapId": map_id,
        "sourceRevision": revision,
        "readOnly": True,
        "frontier": frontier,
        "interactionState": interaction_state,
        "generatedAt": utc_now(),
    }


def build_local_projection(map_document: Mapping[str, Any]) -> dict[str, Any]:
    """Accessible text-first projection when provider visualization is unavailable (R45)."""
    payload = _projection_base(map_document)
    payload.update(
        {
            "mode": "local",
            "visualizationAvailable": False,
            "textFallback": render_accessible_text(payload),
        }
    )
    return sanitize_projection(payload, canonical_map=map_document)


def build_provider_projection(
    map_document: Mapping[str, Any],
    provider_fn: ProviderFn,
) -> dict[str, Any]:
    """Provider-backed projection with semantic parity to the local fallback (R22)."""
    payload = _projection_base(map_document)
    provider_result = provider_fn(map_document)
    verdict = str(provider_result.get("verdict") or "degraded")
    if verdict != "ok":
        local = build_local_projection(map_document)
        local["provider"] = {
            "verdict": verdict,
            "cause": provider_result.get("cause") or provider_result.get("error") or "provider-unavailable",
        }
        local["degradedToLocal"] = True
        return local

    visualization = provider_result.get("visualization")
    payload.update(
        {
            "mode": "provider",
            "visualizationAvailable": visualization is not None,
            "visualization": deepcopy(visualization) if isinstance(visualization, dict) else None,
            "textFallback": render_accessible_text(payload),
            "provider": {"verdict": "ok"},
        }
    )
    return sanitize_projection(payload, canonical_map=map_document)


def render_accessible_text(projection: Mapping[str, Any]) -> str:
    """Plain-text fallback for operators when visualization is unavailable (R45)."""
    map_id = str(projection.get("explorationMapId") or "unknown")
    revision = projection.get("sourceRevision", "?")
    frontier = projection.get("frontier") if isinstance(projection.get("frontier"), dict) else {}
    ready_count = frontier.get("readyCount", 0)
    interaction = projection.get("interactionState")
    lines = [
        f"Exploration map {map_id} at revision {revision}.",
        f"Frontier has {ready_count} open node(s).",
    ]
    if interaction:
        lines.append(f"Interaction state: {interaction} (ask/decide/confirm).")
    summaries = frontier.get("nodeSummaries") if isinstance(frontier.get("nodeSummaries"), list) else []
    open_nodes = [
        item
        for item in summaries
        if isinstance(item, dict) and item.get("status") in OPEN_STATUSES and not item.get("superseded")
    ]
    if open_nodes:
        lines.append("Open nodes:")
        for item in open_nodes[:5]:
            title = str(item.get("title") or item.get("nodeId") or "")
            lines.append(f"- {item.get('nodeId')}: {title}")
    lines.append("Resume exploration with /sw-explore or inspect status via /sw-status.")
    return "\n".join(lines)


def semantic_parity(local: Mapping[str, Any], provider: Mapping[str, Any]) -> dict[str, Any]:
    """Compare provider and local projections on canonical semantic fields (R22)."""
    keys = ("explorationMapId", "sourceRevision", "frontier", "readOnly")
    mismatches: list[str] = []
    for key in keys:
        if local.get(key) != provider.get(key):
            mismatches.append(key)
    return {"verdict": "pass" if not mismatches else "fail", "mismatches": mismatches}


def project_frontier(
    map_document: Mapping[str, Any],
    *,
    provider_fn: ProviderFn | None = None,
) -> dict[str, Any]:
    """Build local projection and optional provider projection without mutating canonical map."""
    local = build_local_projection(map_document)
    result: dict[str, Any] = {
        "verdict": "pass",
        "readOnly": True,
        "local": local,
    }
    if provider_fn is None:
        result["provider"] = None
        result["parity"] = {"verdict": "pass", "note": "provider-not-requested"}
        return result
    provider = build_provider_projection(map_document, provider_fn)
    result["provider"] = provider
    result["parity"] = semantic_parity(local, provider)
    return result


def load_map_from_store(root: Path, map_id: str, *, store: ExplorationStore | None = None) -> dict[str, Any]:
    active_store = store or ExplorationStore(root)
    loaded = active_store.read(map_id)
    if loaded is None:
        raise ExplorationProjectionError("map-not-found")
    return loaded["map"]


def cmd_project(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else Path.cwd()
    map_id = str(args.map_id or "").strip()
    if not map_id:
        print(json.dumps({"verdict": "fail", "error": "missing-map-id"}))
        return 2
    try:
        map_document = load_map_from_store(root, map_id)
        payload = project_frontier(map_document)
    except (ExplorationProjectionError, ExplorationSecurityError) as exc:
        print(json.dumps({"verdict": "fail", "error": str(exc)}))
        return 20
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exploration frontier projections")
    parser.add_argument("--root", default="", help="Repository root (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)

    project = sub.add_parser("project", help="Build local/provider frontier projections")
    project.add_argument("--map-id", required=True)
    project.set_defaults(func=cmd_project)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
