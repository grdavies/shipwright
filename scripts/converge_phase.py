#!/usr/bin/env python3
"""Opt-in deliver converge phase (PRD 342 R42/R43/R55).

Disabled by default. When enabled, reads the planning-unit bundle already bound by
the frozen task list — no second required input. Compiles onto the closed node-kind
registry: assessor as read-only ``gate``, phase body as ``command``. Never uses the
pre-existing execution-retry kind ``convergence-loop``.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from graph.node_kinds import (  # noqa: E402
    CLOSED_NODE_KINDS,
    is_closed_node_kind,
    lookup_node_kind,
)
from shipwright_paths import load_workflow_config  # noqa: E402

# R55 — compile onto existing closed kinds only; never the execution-retry kind.
CONVERGE_ASSESSOR_KIND = "gate"
CONVERGE_PHASE_BODY_KIND = "command"
CONVERGE_FORBIDDEN_RETRY_KIND = "convergence-loop"

CONVERGE_ASSESSOR_NODE_ID = "converge-assess"
CONVERGE_PHASE_NODE_ID = "converge"
CONVERGE_PHASE_SLUG = "converge"
CONVERGE_PHASE_TITLE = "Converge phase composition"

CONFIG_KEY = "converge"


def emit(payload: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


def fail(message: str, exit_code: int = 2, **extra: Any) -> None:
    payload = {"verdict": "fail", "error": message}
    payload.update(extra)
    emit(payload, exit_code)


def is_converge_enabled(root: Path, config: Mapping[str, Any] | None = None) -> bool:
    """Return whether converge is opt-in enabled (default false — R42)."""
    cfg = dict(config) if config is not None else load_workflow_config(root)
    section = cfg.get(CONFIG_KEY)
    if not isinstance(section, dict):
        return False
    return bool(section.get("enabled", False))


def deliver_required_inputs(task_list: str) -> list[str]:
    """Deliver binds exactly one input — the frozen task list (R43)."""
    return [task_list]


def resolve_unit_dir_from_task_list(root: Path, task_list: str) -> Path:
    """Resolve the planning-unit directory already bound by the task list (R43)."""
    import planning_paths as pp

    task_path = Path(task_list)
    if not task_path.is_absolute():
        task_path = root / task_list
    if not task_path.is_file():
        fail(f"task list not found: {task_list}")
    try:
        return pp.prd_unit_dir_for_artifact(root, task_path)
    except Exception:
        return task_path.parent


def converge_plan_item(task_list: str) -> dict[str, Any]:
    """Plan item with the same field shape as deliver phase items."""
    return {
        "id": CONVERGE_PHASE_SLUG,
        "slug": CONVERGE_PHASE_SLUG,
        "title": CONVERGE_PHASE_TITLE,
        "branch": "",
        "files": [],
        "kind": "converge",
        "taskList": task_list,
    }


def maybe_extend_deliver_items(
    root: Path,
    items: list[dict[str, Any]],
    *,
    task_list: str | None = None,
    config: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Append the converge plan item when enabled; otherwise return items unchanged (R42)."""
    if not is_converge_enabled(root, config):
        return items
    if not task_list:
        return items
    extended = list(items)
    if any(str(item.get("slug") or "") == CONVERGE_PHASE_SLUG for item in extended):
        return extended
    extended.append(converge_plan_item(task_list))
    return extended


def deliver_phase_sequence(
    root: Path,
    phase_items: list[dict[str, Any]],
    *,
    task_list: str | None = None,
    config: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return ordered phase slugs for deliver (baseline when converge disabled)."""
    items = maybe_extend_deliver_items(
        root, list(phase_items), task_list=task_list, config=config
    )
    return [str(item.get("slug") or item.get("id") or "") for item in items]


def _clone_node_template(
    template: Mapping[str, Any], node_id: str, kind: str
) -> dict[str, Any]:
    node = copy.deepcopy(dict(template))
    node["id"] = node_id
    node["kind"] = kind
    target = dict(node.get("target") or {})
    target["step"] = node_id
    node["target"] = target
    if kind == CONVERGE_ASSESSOR_KIND:
        node["resources"] = {
            "pool": "read-only-reviewers",
            "slots": 1,
            "timeoutSeconds": 1800,
        }
        node["isolation"] = {"mode": "process", "writeScope": "read-only"}
        node["execution"] = {"purity": "read-only", "cache": "disabled"}
    else:
        node["resources"] = {
            "pool": "code-writers",
            "slots": 1,
            "timeoutSeconds": 3600,
        }
        node["isolation"] = {"mode": "worktree", "writeScope": "worktree"}
        node["execution"] = {"purity": "mutating", "cache": "disabled"}
    node["verification"] = {"required": True, "strategy": "mechanical"}
    return node


def compile_converge_nodes(
    template: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Compile assessor (gate) + phase body (command). No new node kinds (R55)."""
    if CONVERGE_ASSESSOR_KIND == CONVERGE_FORBIDDEN_RETRY_KIND:
        raise RuntimeError("converge assessor must not use the execution-retry kind")
    if CONVERGE_PHASE_BODY_KIND == CONVERGE_FORBIDDEN_RETRY_KIND:
        raise RuntimeError("converge phase body must not use the execution-retry kind")
    for kind in (CONVERGE_ASSESSOR_KIND, CONVERGE_PHASE_BODY_KIND):
        if not is_closed_node_kind(kind):
            raise RuntimeError(f"converge kind outside closed registry: {kind}")
    assessor_spec = lookup_node_kind(CONVERGE_ASSESSOR_KIND)
    if assessor_spec is None or not assessor_spec.read_only:
        raise RuntimeError("converge assessor must compile as a read-only gate")

    if template is None:
        template = {
            "id": "template",
            "kind": "command",
            "target": {"step": "template"},
            "resources": {
                "pool": "code-writers",
                "slots": 1,
                "timeoutSeconds": 3600,
            },
            "isolation": {"mode": "worktree", "writeScope": "worktree"},
            "verification": {"required": True, "strategy": "mechanical"},
            "execution": {"purity": "mutating", "cache": "disabled"},
        }
    assessor = _clone_node_template(
        template, CONVERGE_ASSESSOR_NODE_ID, CONVERGE_ASSESSOR_KIND
    )
    body = _clone_node_template(
        template, CONVERGE_PHASE_NODE_ID, CONVERGE_PHASE_BODY_KIND
    )
    # slug/title are explain-plan projections only — not WorkflowGraph node fields.
    return [assessor, body]


def converge_node_kinds_used() -> frozenset[str]:
    return frozenset({CONVERGE_ASSESSOR_KIND, CONVERGE_PHASE_BODY_KIND})


def assert_converge_kinds_closed(nodes: list[Mapping[str, Any]]) -> None:
    kinds = {str(node.get("kind") or "") for node in nodes}
    unknown = kinds - CLOSED_NODE_KINDS
    if unknown:
        raise AssertionError(
            f"converge graph has kinds outside closed registry: {sorted(unknown)}"
        )
    if CONVERGE_FORBIDDEN_RETRY_KIND in kinds:
        raise AssertionError(
            "converge must not be named as the pre-existing execution-retry kind "
            f"{CONVERGE_FORBIDDEN_RETRY_KIND!r}"
        )


def maybe_attach_converge_nodes(
    root: Path,
    graph: dict[str, Any],
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach converge gate+command nodes when enabled; otherwise return graph as-is."""
    if not is_converge_enabled(root, config):
        return graph
    spec = graph.get("spec")
    if not isinstance(spec, dict):
        return graph
    nodes = list(spec.get("nodes") or [])
    if any(str(node.get("id")) == CONVERGE_PHASE_NODE_ID for node in nodes):
        return graph
    template = nodes[-1] if nodes else None
    converge_nodes = compile_converge_nodes(template)
    assert_converge_kinds_closed(converge_nodes)

    edges = list(spec.get("edges") or [])
    if nodes:
        edges.append(
            {
                "from": str(nodes[-1]["id"]),
                "to": CONVERGE_ASSESSOR_NODE_ID,
                "required": True,
            }
        )
    edges.append(
        {
            "from": CONVERGE_ASSESSOR_NODE_ID,
            "to": CONVERGE_PHASE_NODE_ID,
            "required": True,
        }
    )
    updated = copy.deepcopy(graph)
    updated_spec = dict(updated.get("spec") or {})
    updated_spec["nodes"] = nodes + converge_nodes
    updated_spec["edges"] = edges
    updated["spec"] = updated_spec
    return updated


_EXPLAIN_LABELS = {
    CONVERGE_ASSESSOR_NODE_ID: {
        "slug": CONVERGE_ASSESSOR_NODE_ID,
        "title": "Converge assessor",
    },
    CONVERGE_PHASE_NODE_ID: {
        "slug": CONVERGE_PHASE_SLUG,
        "title": CONVERGE_PHASE_TITLE,
    },
}


def explain_plan_nodes(graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project graph nodes into the explain-plan node field shape."""
    spec = graph.get("spec") if isinstance(graph.get("spec"), Mapping) else {}
    nodes = spec.get("nodes") if isinstance(spec, Mapping) else None
    if not isinstance(nodes, list):
        return []
    projected: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        node_id = str(node.get("id") or "")
        labels = _EXPLAIN_LABELS.get(node_id, {})
        target = node.get("target") if isinstance(node.get("target"), Mapping) else {}
        step = str(target.get("step") or node_id)
        projected.append(
            {
                "id": node_id,
                "kind": str(node.get("kind") or ""),
                "slug": str(labels.get("slug") or node.get("slug") or step or node_id),
                "title": str(
                    labels.get("title")
                    or node.get("title")
                    or node.get("slug")
                    or step
                    or node_id
                ),
            }
        )
    return projected


def node_progress_from_status_explain(
    status_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Read per-node progress from status explain / live status payloads (R55)."""
    nodes = status_payload.get("nodes")
    if not isinstance(nodes, list):
        node_id = status_payload.get("nodeId")
        if node_id:
            return [
                {
                    "nodeId": str(node_id),
                    "state": str(status_payload.get("state") or "unknown"),
                }
            ]
        return []
    progress: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, Mapping):
            continue
        progress.append(
            {
                "nodeId": str(node.get("nodeId") or node.get("id") or ""),
                "state": str(node.get("state") or "unknown"),
            }
        )
    return progress


def run_converge_phase(
    root: Path,
    *,
    task_list: str,
    phase_id: str | None = None,
    phase_slug: str | None = None,
    skip_verify_execute: bool = True,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute the converge phase for a unit already bound by the frozen task list."""
    if not is_converge_enabled(root, config):
        return {
            "verdict": "skipped",
            "reason": "converge.disabled",
            "enabled": False,
            "requiredInputs": deliver_required_inputs(task_list),
        }
    unit_dir = resolve_unit_dir_from_task_list(root, task_list)
    from converge_assess import compose_converge_assessment

    assessment = compose_converge_assessment(
        root,
        task_list=task_list,
        unit_dir=unit_dir,
        phase_id=phase_id,
        phase_slug=phase_slug,
        skip_verify_execute=skip_verify_execute,
    )
    nodes = compile_converge_nodes()
    assert_converge_kinds_closed(nodes)
    return {
        "verdict": "pass",
        "enabled": True,
        "blocksRun": False,
        "requiredInputs": deliver_required_inputs(task_list),
        "unitDir": str(unit_dir),
        "assessment": assessment,
        "findingRouting": assessment.get("findingRouting"),
        "autoFixApplied": False,
        "autoAmendApplied": False,
        "nodes": explain_plan_nodes({"spec": {"nodes": nodes}}),
        "nodeKinds": sorted(converge_node_kinds_used()),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Opt-in deliver converge phase (PRD 342)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run converge for the unit bound by --task-list")
    run_p.add_argument("--root", default=".")
    run_p.add_argument("--task-list", required=True)
    run_p.add_argument("--phase-id")
    run_p.add_argument("--phase-slug")
    run_p.add_argument("--execute-verify", action="store_true")

    status_p = sub.add_parser("enabled", help="Report whether converge is enabled")
    status_p.add_argument("--root", default=".")

    args = parser.parse_args(argv)
    root = Path(getattr(args, "root", ".")).resolve()
    if args.command == "enabled":
        emit(
            {
                "verdict": "pass",
                "enabled": is_converge_enabled(root),
                "default": False,
            }
        )
    if args.command == "run":
        result = run_converge_phase(
            root,
            task_list=args.task_list,
            phase_id=args.phase_id,
            phase_slug=args.phase_slug,
            skip_verify_execute=not bool(args.execute_verify),
        )
        emit(result, 0 if result.get("verdict") in {"pass", "skipped"} else 1)
    fail(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
