#!/usr/bin/env python3
"""Backend-pluggable planning unit discovery (PRD 046 R83, R87)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Literal

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_gen as pig  # noqa: E402
import planning_paths as pp  # noqa: E402
from host_lib import load_workflow_config  # noqa: E402
from issues_lib import IssuesClient  # noqa: E402
from planning_canonical import (  # noqa: E402
    MARKER_ARTIFACT_TYPE,
    MARKER_UNIT_ID,
    infer_artifact_type,
    parse_body_marker,
    parse_edges_block,
    reassemble_body,
    strip_markers_and_edges,
)
from planning_store import resolve_effective_backend, validate_project_key  # noqa: E402

DiscoverSource = Literal["file", "issue"]
PINNED_STATE_REL = ".cursor/hooks/state/planning-discover-pinned.json"
EDGE_KEYS = pig.EDGE_KEYS
UNIT_TYPES = pig.UNIT_TYPES

_VISIBILITY_LABEL_PREFIX = "sw:visibility:"


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def pinned_state_path(root: Path) -> Path:
    return pp.git_root(root) / PINNED_STATE_REL


def load_pinned_source(root: Path) -> DiscoverSource | None:
    path = pinned_state_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    source = str(data.get("source", "")).strip().lower()
    if source in {"file", "issue"}:
        return source
    return None


def pin_discover_source(root: Path, source: DiscoverSource) -> None:
    path = pinned_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "source": source}, indent=2) + "\n",
        encoding="utf-8",
    )


def resolve_discover_source(root: Path) -> DiscoverSource:
    env = os.environ.get("SW_DISCOVER_SOURCE", "").strip().lower()
    if env in {"file", "issue"}:
        return env
    pinned = load_pinned_source(root)
    if pinned:
        return pinned
    worktree = pp.git_root(root)
    cfg = load_workflow_config(worktree)
    effective = resolve_effective_backend(worktree, cfg)
    if effective.get("effective") != "issue-store":
        return "file"
    from planning_cutover import load_cutover_gate

    gate = load_cutover_gate(worktree)
    if gate.get("discoverSource") == "issue":
        return "issue"
    return "file"


def discover_units_file(root: Path) -> list[pig.PlanningUnit]:
    worktree = pp.git_root(root)
    dirs = pp.load_planning_dirs(root)
    planning_root = worktree / dirs.planning
    if not planning_root.is_dir():
        return []
    units: list[pig.PlanningUnit] = []
    for type_dir in sorted(planning_root.iterdir()):
        if not type_dir.is_dir() or type_dir.name.startswith("."):
            continue
        if type_dir.name not in UNIT_TYPES:
            continue
        for unit_dir in sorted(type_dir.iterdir()):
            if not unit_dir.is_dir():
                continue
            body = pig.body_file_for_unit_dir(unit_dir)
            if not body:
                continue
            fm = pig.parse_frontmatter(body.read_text(encoding="utf-8"))
            if not fm:
                continue
            unit_id = str(fm.get("id", "")).strip()
            if not unit_id:
                continue
            edge_map = {key: fm.get(key) for key in EDGE_KEYS if fm.get(key)}
            units.append(
                pig.PlanningUnit(
                    id=unit_id,
                    type=str(fm.get("type", type_dir.name)),
                    status=str(fm.get("status", "")),
                    title=str(fm.get("title", "")),
                    visibility=str(fm.get("visibility", "")),
                    edges=pig.format_edges(fm),
                    body_path=str(body.relative_to(worktree)),
                    opaque_title=pig.parse_opaque_title(fm.get("opaqueTitle")),
                    edge_map=edge_map or None,
                )
            )
    units.sort(key=lambda u: (u.type, u.id))
    return units


def _visibility_from_labels(labels: list[str]) -> str:
    for label in labels:
        if label.startswith(_VISIBILITY_LABEL_PREFIX):
            return label[len(_VISIBILITY_LABEL_PREFIX) :]
    return ""


def _gap_status_from_labels(labels: list[str]) -> str:
    if "sw:gap-resolved" in labels:
        return "resolved"
    if "sw:gap-scheduled" in labels:
        return "scheduled"
    if "sw:gap-open" in labels:
        return "open"
    return "open"


def _title_from_record(record: Any) -> str:
    title = str(record.title or "")
    if ":" in title:
        _, _, tail = title.partition(":")
        tail = tail.strip()
        if tail:
            return tail
    return title


def _status_from_record(record: Any, content: str) -> str:
    artifact_type = record.artifact_type or infer_artifact_type(record.unit_id)
    if artifact_type == "gap":
        return _gap_status_from_labels(list(record.labels))
    if content.startswith("---"):
        fm = pig.parse_frontmatter(content)
        if fm and fm.get("status"):
            return str(fm["status"])
    if record.state == "closed":
        return "complete"
    return "proposed"


def _edges_from_record(record: Any, content: str) -> dict[str, Any]:
    full_body = reassemble_body(record.body, record.comments)
    edges_data = parse_edges_block(full_body)
    if edges_data and edges_data.get("edges"):
        edge_map: dict[str, Any] = {}
        for edge in edges_data.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            rel = str(edge.get("rel", "")).strip()
            target = edge.get("target")
            if not rel or not target:
                continue
            key = {
                "depends": "depends",
                "blocks": "blocks",
                "supersedes": "supersedes",
                "extends": "extends",
                "absorbs": "absorbs",
            }.get(rel, rel)
            existing = edge_map.get(key)
            if existing is None:
                edge_map[key] = target
            elif isinstance(existing, list):
                existing.append(target)
            else:
                edge_map[key] = [existing, target]
        return edge_map
    if content.startswith("---"):
        fm = pig.parse_frontmatter(content)
        if fm:
            return {key: fm.get(key) for key in EDGE_KEYS if fm.get(key)}
    return {}


def _issue_record_to_unit(root: Path, record: Any) -> pig.PlanningUnit | None:
    unit_id = str(record.unit_id or "").strip()
    if not unit_id:
        unit_id = parse_body_marker(record.body, MARKER_UNIT_ID) or ""
    if not unit_id:
        return None
    artifact_type = str(record.artifact_type or "").strip()
    if not artifact_type:
        artifact_type = parse_body_marker(record.body, MARKER_ARTIFACT_TYPE) or infer_artifact_type(unit_id)
    if artifact_type not in UNIT_TYPES:
        return None
    content = strip_markers_and_edges(reassemble_body(record.body, record.comments))
    visibility = _visibility_from_labels(list(record.labels))
    if not visibility and content.startswith("---"):
        fm = pig.parse_frontmatter(content)
        if fm:
            visibility = str(fm.get("visibility", ""))
    edge_map = _edges_from_record(record, content)
    status = _status_from_record(record, content)
    title = _title_from_record(record)
    if content.startswith("---"):
        fm = pig.parse_frontmatter(content)
        if fm:
            if fm.get("title"):
                title = str(fm["title"])
            if fm.get("visibility") and not visibility:
                visibility = str(fm["visibility"])
    body_path = f"issue:{record.id}"
    return pig.PlanningUnit(
        id=unit_id,
        type=artifact_type,
        status=status,
        title=title,
        visibility=visibility,
        edges=pig.format_edges(edge_map) if edge_map else "",
        body_path=body_path,
        opaque_title=False,
        edge_map=edge_map or None,
    )


def discover_units_issue(root: Path) -> list[pig.PlanningUnit]:
    worktree = pp.git_root(root)
    cfg = load_workflow_config(worktree)
    key_result = validate_project_key(worktree, cfg)
    if key_result.get("verdict") != "ok":
        return []
    project_key = str(key_result["projectKey"])
    store = (cfg.get("planning") or {}).get("store") or {}
    provider = str(store.get("issuesProvider", "none"))
    client = IssuesClient(worktree, provider)
    records = client.issue_search(project_key=project_key)
    units: list[pig.PlanningUnit] = []
    for record in records:
        unit = _issue_record_to_unit(worktree, record)
        if unit:
            units.append(unit)
    units.sort(key=lambda u: (u.type, u.id))
    return units


def discover_units(root: Path) -> list[pig.PlanningUnit]:
    source = resolve_discover_source(root)
    if source == "issue":
        return discover_units_issue(root)
    return discover_units_file(root)


def cmd_resolve(root: Path, _args: list[str]) -> None:
    emit(
        {
            "verdict": "pass",
            "action": "resolve-discover-source",
            "source": resolve_discover_source(root),
        }
    )


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        fail("usage: planning_discover.py <repo-root> <command>")
    root = Path(args[0]).resolve()
    command = args[1]
    if command == "resolve":
        cmd_resolve(root, args[2:])
    else:
        fail(f"unknown command: {command}")


if __name__ == "__main__":
    main()
