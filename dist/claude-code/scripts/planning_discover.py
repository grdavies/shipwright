#!/usr/bin/env python3
"""Backend-pluggable planning unit discovery (PRD 046 R83, R87)."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Literal

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_gen as pig  # noqa: E402
import planning_visibility as pv  # noqa: E402
import planning_paths as pp  # noqa: E402
from host_lib import load_workflow_config  # noqa: E402
from issues_lib import IssuesClient  # noqa: E402
from planning_canonical import (  # noqa: E402
    artifact_type_from_content,
    artifact_type_from_labels,
    gap_schedule_from_labels,
    gap_status_from_labels,
    require_artifact_type,
    source_tag_from_labels,
    status_from_labels,
    MARKER_ARTIFACT_TYPE,
    MARKER_UNIT_ID,
    infer_artifact_type,
    parse_body_marker,
    parse_edges_block,
    reassemble_body,
    strip_markers_and_edges,
)
from planning_cutover import load_cutover_gate  # noqa: E402
from planning_store import validate_project_key  # noqa: E402
from planning_request_budget import BudgetExhausted, RequestBudgetLedger  # noqa: E402
from planning_query_cache import (  # noqa: E402
    DEFAULT_QUERY_FINGERPRINT,
    get_entry,
    invalidate_all,
    put_entry,
    query_fingerprint,
    resolve_ttl,
    revalidate_live_metadata,
)
from secret_scan import load_allowlist, scan_text  # noqa: E402

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
    # PRD 057 R5: load_cutover_gate derives the default from committed config (effective
    # backend) + structural markers — no gitignored-state-file dependency for CI correctness.
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
                    source=str(fm.get("source", "")).strip(),
                    schedule=str(fm.get("schedule", "")).strip(),
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
    mapped = gap_status_from_labels(labels)
    if mapped == "resolved":
        return "resolved"
    if mapped == "planned":
        return "scheduled"
    if mapped == "open":
        return "open"
    return "open"


# PRD 057 R11 -- matches only the pre-R11 `[project] type:unit-id` issue
# title format (see `planning_canonical.title_prefix`). A post-R11
# human-readable title (`planning_canonical.human_readable_title`) never
# starts with a bracketed project prefix, so it is returned unchanged below
# even when it legitimately contains a colon (e.g. "Fix: race condition").
_LEGACY_BRACKETED_TITLE_RE = re.compile(r"^\[[^\]]+\]\s+[A-Za-z][\w-]*:(.+)$")


def _title_from_record(record: Any) -> str:
    title = str(record.title or "")
    match = _LEGACY_BRACKETED_TITLE_RE.match(title)
    if match:
        tail = match.group(1).strip()
        if tail:
            return tail
    return title


def _status_from_record(record: Any, content: str) -> str:
    artifact_type = (
        record.artifact_type
        or artifact_type_from_labels(list(record.labels))
        or artifact_type_from_content(content)
        or require_artifact_type(record.unit_id, content=content)
    )
    if artifact_type == "brainstorm":
        labeled = status_from_labels(list(record.labels))
        return labeled or "complete"
    if artifact_type == "gap":
        return _gap_status_from_labels(list(record.labels))
    if artifact_type == "tasks":
        labeled = status_from_labels(list(record.labels))
        return labeled or ("complete" if record.state == "closed" else "in-progress")
    labeled = status_from_labels(list(record.labels))
    if labeled:
        return labeled
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
                "prd": "prd",
                "amends": "amends",
                "brainstorm": "brainstorm",
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
    # PRD 057 R12/R17 -- provider-native label is authoritative; frontmatter is
    # the dual-read fallback (same precedence as `visibility` above).
    source = source_tag_from_labels(list(record.labels))
    schedule = gap_schedule_from_labels(list(record.labels))
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
            if fm.get("source") and not source:
                source = str(fm["source"]).strip()
            if fm.get("schedule") and not schedule:
                schedule = str(fm["schedule"]).strip()
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
        source=source,
        schedule=schedule,
    )


def _scan_issue_ingest(worktree: Path, record: Any) -> None:
    """Secret-scan chokepoint before redaction/cache (PRD 043 R45, 046 R84)."""
    from planning_canonical import reassemble_body

    body = reassemble_body(record.body, record.comments)
    allowlist = load_allowlist(worktree)
    findings = scan_text(body, allowlist=allowlist, path=f"issue:{record.id}")
    if findings:
        fail("secret-scan: issue-derived ingest blocked", exit_code=20, issueId=record.id)


def _projection_from_unit(unit: pig.PlanningUnit, root: Path) -> dict[str, Any]:
    row = pig.index_row_dict(unit, root)
    return {
        "id": row["id"],
        "type": row["type"],
        "title": row.get("title", ""),
        "status": row.get("status", ""),
        "visibility": row.get("visibility", ""),
        "edges": unit.edges,
        "source": unit.source,
        "schedule": unit.schedule,
    }


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
    ledger = RequestBudgetLedger.from_config(root, provider)
    fingerprint = query_fingerprint(project_key)
    force_refresh = os.environ.get("SW_PLANNING_FORCE_REFRESH", "").strip().lower() in {"1", "true", "yes"}
    if not force_refresh:
        cached = get_entry(root, project_key=project_key, fingerprint=fingerprint, ttl_seconds=resolve_ttl(root, provider))
        if cached and isinstance(cached.get("projections"), list):
            ledger.charge("discover-revalidate", critical=True)
            if revalidate_live_metadata(root, client, cached):
                units: list[pig.PlanningUnit] = []
                for proj in cached["projections"]:
                    if not isinstance(proj, dict) or not proj.get("id"):
                        continue
                    units.append(
                        pig.PlanningUnit(
                            id=str(proj["id"]),
                            type=str(proj.get("type", "")),
                            status=str(proj.get("status", "")),
                            title=str(proj.get("title", "")),
                            visibility=str(proj.get("visibility", "")),
                            edges=str(proj.get("edges", "")),
                            body_path=f"issue-cache:{proj['id']}",
                            opaque_title=bool(proj.get("opaqueTitle")),
                            source=str(proj.get("source", "")),
                            schedule=str(proj.get("schedule", "")),
                        )
                    )
                if units:
                    units.sort(key=lambda u: (u.type, u.id))
                    return units
            else:
                # Symmetric-diff / state drift detected — the cache is stale
                # for every fingerprint, not just this query (R10).
                invalidate_all(root)
    ledger.charge("issue-search")
    all_records = list(client.issue_search(project_key=project_key))
    page_size_raw = os.environ.get("SW_ISSUES_PAGE_SIZE", "").strip()
    page_size = int(page_size_raw) if page_size_raw.isdigit() else 0
    max_pages = ledger.max_pagination_depth
    if page_size > 0:
        pages_needed = (len(all_records) + page_size - 1) // page_size
        if pages_needed > max_pages:
            pig.mark_index_incomplete(root, "index-incomplete: pagination ceiling with hasNextPage")
            fail("index-incomplete: pagination ceiling reached", exit_code=20, hasNextPage=True)
        records = all_records[:page_size]
        if len(all_records) > page_size:
            pig.mark_index_incomplete(root, "index-incomplete: pagination ceiling with hasNextPage")
            fail("index-incomplete: pagination ceiling reached", exit_code=20, hasNextPage=True)
    else:
        records = all_records
    units = []
    metadata_units: dict[str, Any] = {}
    projections: list[dict[str, Any]] = []
    for record in records:
        _scan_issue_ingest(worktree, record)
        unit = _issue_record_to_unit(worktree, record)
        if not unit:
            continue
        vis = pig.resolved_visibility(unit, root)
        if pv.body_is_redacted(vis):
            unit = pig.PlanningUnit(
                id=unit.id,
                type=unit.type,
                status=unit.status,
                title=f"{unit.id}: [private]",
                visibility=vis,
                edges="",
                body_path=unit.body_path,
                opaque_title=True,
                edge_map=None,
                source=unit.source,
                schedule=unit.schedule,
            )
        units.append(unit)
        metadata_units[unit.id] = {"state": record.state, "labels": sorted(record.labels)}
        projections.append(_projection_from_unit(unit, root))
    put_entry(root, project_key=project_key, fingerprint=fingerprint, projections=projections, metadata={"units": metadata_units})
    units.sort(key=lambda u: (u.type, u.id))
    return units


def discover_units(root: Path) -> list[pig.PlanningUnit]:
    source = resolve_discover_source(root)
    if source == "issue":
        try:
            return discover_units_issue(root)
        except BudgetExhausted as exc:
            pig.mark_index_incomplete(root, str(exc))
            fail(str(exc), exit_code=20, indexIncomplete=True)
    return discover_units_file(root)


_SOURCE_SCOPE_ENV = "SW_PLANNING_SOURCE_SCOPE"


def resolve_source_scope(root: Path) -> list[str]:
    """PRD 057 R12 -- explicit `sw:source:<owner>/<repo>` scope for a shared
    planning repository.

    An env override (comma-separated, for one-off CLI invocations) takes
    precedence over `planning.store.sourceScope` in committed config. An empty
    result (the default) means every source is in scope -- see
    `filter_units_by_source` for the untagged-legacy-unit guarantee this pairs
    with, and `planning-doctor.py`'s `sw:source-missing` finding for the
    companion advisory.
    """
    env = os.environ.get(_SOURCE_SCOPE_ENV, "").strip()
    if env:
        return [s.strip() for s in env.split(",") if s.strip()]
    worktree = pp.git_root(root)
    cfg = load_workflow_config(worktree)
    store = (cfg.get("planning") or {}).get("store") or {}
    scope = store.get("sourceScope")
    if isinstance(scope, list):
        return [str(s).strip() for s in scope if str(s).strip()]
    if isinstance(scope, str) and scope.strip():
        return [scope.strip()]
    return []


def filter_units_by_source(units: list[Any], scope: list[str]) -> list[Any]:
    """PRD 057 R12 -- scope discovery/scheduler/gap-capture to `sw:source:*`.

    A non-empty scope keeps every unit tagged with a matching source AND every
    untagged legacy unit -- scoping never silently hides an untagged unit
    (that gap is instead surfaced via the `sw:source-missing` doctor finding).
    An empty scope (the default) is a no-op. Generic over any sequence of
    objects exposing a `.source` attribute (`planning_index_gen.PlanningUnit`
    or `planning_graph.GraphUnit`).
    """
    if not scope:
        return units
    scope_set = set(scope)
    return [u for u in units if not getattr(u, "source", "") or u.source in scope_set]


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
