#!/usr/bin/env python3
"""Epic/sub-issue hierarchy with checkbox fallback (PRD 046 R23, R91, R94)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import doc_format  # noqa: E402
import planning_paths as pp  # noqa: E402
from host_lib import load_workflow_config  # noqa: E402
from issues_lib import IssuesClient  # noqa: E402
from planning_canonical import compose_issue_body, native_links_from_edges, project_label, type_label  # noqa: E402
from planning_store import (  # noqa: E402
    issue_index_key,
    load_issue_unit_index,
    resolve_effective_backend,
    save_issue_unit_index,
    store_section,
)

HIERARCHY_VERBS = frozenset({
    "issue-epic-create",
    "issue-sub-issue-create",
    "issue-sub-issue-update",
    "issue-sub-issue-link",
})

HIERARCHY_MATRIX: dict[str, dict[str, str]] = {
    "github-issues": {
        "issue-epic-create": "REST",
        "issue-sub-issue-create": "REST",
        "issue-sub-issue-update": "REST",
        "issue-sub-issue-link": "REST",
    },
    "gitlab-issues": {
        "issue-epic-create": "REST",
        "issue-sub-issue-create": "REST",
        "issue-sub-issue-update": "REST",
        "issue-sub-issue-link": "REST",
    },
    "jira": {
        "issue-epic-create": "pending",
        "issue-sub-issue-create": "pending",
        "issue-sub-issue-update": "pending",
        "issue-sub-issue-link": "pending",
    },
    "none": {},
}

TIER_LABEL = re.compile(r"^sw:tier:(.+)$")
STATUS_LABEL = re.compile(r"^sw:status:(.+)$")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def parse_task_list_phases(task_list: Path | str, *, content: str | None = None) -> list[dict[str, str]]:
    """Parse ### N. phase headings from a frozen task list (R23)."""
    if content is None:
        text = Path(task_list).read_text(encoding="utf-8")
    else:
        text = content
    return doc_format.extract_phases(text)


def hierarchy_capability_matrix() -> dict[str, dict[str, str]]:
    """Per-provider epic/sub-issue verb table (R94)."""
    return {provider: dict(verbs) for provider, verbs in HIERARCHY_MATRIX.items()}


def resolve_hierarchy_mode(provider: str) -> dict[str, Any]:
    """Choose epic-sub-issue vs checkbox/body fallback (R23, R94)."""
    caps = HIERARCHY_MATRIX.get(provider, {})
    required = ("issue-epic-create", "issue-sub-issue-create")
    if all(caps.get(verb) == "REST" for verb in required):
        return {
            "verdict": "ok",
            "mode": "epic-sub-issue",
            "provider": provider,
            "notice": None,
        }
    notice = (
        f"hierarchy verbs absent for {provider!r}; "
        "degrading to checkbox/body-encoded phase list — deliver continues"
    )
    return {
        "verdict": "ok",
        "mode": "checkbox",
        "provider": provider,
        "notice": notice,
    }


def hierarchy_epic_sub_issues_opt_in(cfg: dict[str, Any]) -> bool:
    """Opt-in epic+per-phase sub-issue mint (PRD 061 R8). Default false."""
    store = store_section(cfg)
    hierarchy = store.get("hierarchy")
    if isinstance(hierarchy, dict):
        return hierarchy.get("epicSubIssues") is True
    return False


def resolve_progress_hierarchy_mode(provider: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Default parent-checkbox on capable providers; epic-sub-issue opt-in only (PRD 061 R6–R8)."""
    cap = resolve_hierarchy_mode(provider)
    if cap["mode"] == "checkbox":
        return cap
    if hierarchy_epic_sub_issues_opt_in(cfg):
        return cap
    return {
        "verdict": "ok",
        "mode": "parent-checkbox",
        "provider": provider,
        "notice": None,
    }


def build_checkbox_phase_block(
    phases: list[dict[str, str]],
    checked_ids: list[str] | None = None,
) -> str:
    """Portable checkbox-encoded phase list for body fallback (R23)."""
    checked = set(checked_ids or [])
    lines = ["## Phase checklist (body-encoded fallback)", ""]
    for phase in phases:
        pid = phase.get("id", "")
        title = phase.get("title", "")
        mark = "x" if pid in checked else " "
        lines.append(f"- [{mark}] Phase {pid}: {title}")
    lines.append("")
    lines.append("```sw-edges")
    lines.append("children:")
    for phase in phases:
        lines.append(f"  - phase:{phase.get('id', '')}")
    lines.append("```")
    return "\n".join(lines)


def _label_value(labels: list[str], pattern: re.Pattern[str]) -> str | None:
    for label in labels:
        m = pattern.match(label)
        if m:
            return m.group(1)
    return None


def _child_record(raw: dict[str, Any]) -> dict[str, Any]:
    labels = [str(x) for x in (raw.get("labels") or [])]
    return {
        "id": raw.get("id") or raw.get("unitId") or raw.get("phaseId"),
        "state": str(raw.get("state", "open")),
        "tier": _label_value(labels, TIER_LABEL),
        "status": _label_value(labels, STATUS_LABEL),
        "labels": labels,
    }


def aggregate_parent_status(
    parent: dict[str, Any],
    children: list[dict[str, Any]],
) -> dict[str, Any]:
    """Aggregate epic/parent status from children; fail-closed on conflict (R91)."""
    parent_labels = [str(x) for x in (parent.get("labels") or [])]
    parent_tier = _label_value(parent_labels, TIER_LABEL)
    parent_status = _label_value(parent_labels, STATUS_LABEL) or str(parent.get("status", ""))
    parent_state = str(parent.get("state", "open"))

    child_rows = [_child_record(c) for c in children]
    child_tiers = {c["tier"] for c in child_rows if c.get("tier")}
    child_statuses = {c["status"] for c in child_rows if c.get("status")}
    child_states = [c["state"] for c in child_rows]

    conflicts: list[dict[str, Any]] = []
    if len(child_tiers) > 1:
        conflicts.append({"kind": "child-tier-split", "tiers": sorted(child_tiers)})
    if len(child_statuses) > 1:
        conflicts.append({"kind": "child-status-split", "statuses": sorted(child_statuses)})
    unanimous_tier = next(iter(child_tiers)) if len(child_tiers) == 1 else None
    unanimous_status = next(iter(child_statuses)) if len(child_statuses) == 1 else None
    if parent_tier and unanimous_tier and parent_tier != unanimous_tier:
        conflicts.append({
            "kind": "parent-child-tier",
            "parentTier": parent_tier,
            "childTier": unanimous_tier,
        })
    if parent_status and unanimous_status and parent_status != unanimous_status:
        conflicts.append({
            "kind": "parent-child-status",
            "parentStatus": parent_status,
            "childStatus": unanimous_status,
        })

    if conflicts:
        return {
            "verdict": "fail",
            "error": "hierarchy-status-conflict",
            "conflicts": conflicts,
            "failClosed": True,
        }

    aggregated_state = "closed" if child_states and all(s == "closed" for s in child_states) else "open"
    aggregated_status = unanimous_status or parent_status or "proposed"
    aggregated_tier = unanimous_tier or parent_tier

    return {
        "verdict": "ok",
        "aggregated": {
            "state": aggregated_state,
            "status": aggregated_status,
            "tier": aggregated_tier,
        },
        "childCount": len(child_rows),
    }


def reconcile_hierarchy_on_read(
    *,
    sw_edges: dict[str, Any] | None,
    native_links: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """sw-edges authoritative on conflict; native links reconciled on read (R91)."""
    edges = sw_edges if isinstance(sw_edges, dict) else {}
    native = list(native_links or [])
    edge_children = list(edges.get("children") or edges.get("subIssues") or [])
    native_children = [
        link.get("target") or link.get("id") or link.get("unitId")
        for link in native
        if isinstance(link, dict)
    ]
    native_children = [str(x) for x in native_children if x]

    authoritative = [str(x) for x in edge_children]
    reconciled_native = [c for c in native_children if c in authoritative or not authoritative]
    conflict = bool(authoritative and native_children and set(reconciled_native) != set(native_children))

    return {
        "verdict": "ok",
        "authoritative": "sw-edges",
        "children": authoritative or reconciled_native,
        "nativeLinks": native_children,
        "reconciledNative": reconciled_native,
        "conflict": conflict,
        "projectionOnly": bool(native_children),
    }


def _issues_provider(root: Path) -> str:
    cfg = load_workflow_config(root)
    store = store_section(cfg)
    provider = store.get("issuesProvider")
    if isinstance(provider, str) and provider.strip():
        return provider.strip()
    return "none"


def _project_key(root: Path) -> str:
    cfg = load_workflow_config(root)
    store = store_section(cfg)
    key = store.get("projectKey")
    if isinstance(key, str) and key.strip():
        return key.strip()
    return "default"


def project_task_list_hierarchy(
    root: Path,
    task_list: Path,
    *,
    unit_id: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Map frozen task list to epic + sub-issues or checkbox body block (R23)."""
    worktree = pp.git_root(root)
    cfg = load_workflow_config(worktree)
    provider = _issues_provider(worktree)
    mode_info = resolve_progress_hierarchy_mode(provider, cfg)
    phases = parse_task_list_phases(task_list)
    if not phases:
        return {"verdict": "fail", "error": "no-phases-in-task-list"}

    project_key = _project_key(worktree)
    uid = unit_id or task_list.stem.replace("tasks-", "", 1)
    result: dict[str, Any] = {
        "verdict": "ok",
        "mode": mode_info["mode"],
        "provider": provider,
        "projectKey": project_key,
        "unitId": uid,
        "phaseCount": len(phases),
        "dryRun": dry_run,
    }
    if mode_info.get("notice"):
        result["notice"] = mode_info["notice"]

    checkbox_block = build_checkbox_phase_block(phases)
    result["phases"] = phases
    if mode_info["mode"] == "checkbox":
        result["checkboxBlock"] = checkbox_block
        result["projection"] = {"kind": "checkbox-body", "phases": phases}
        return result

    plan: dict[str, Any] = {
        "epic": {
            "title": f"[sw] tasks:{uid}",
            "artifactType": "tasks",
            "unitId": uid,
        },
        "phases": phases,
    }
    if mode_info["mode"] == "epic-sub-issue":
        plan["subIssues"] = [
            {
                "phaseId": p["id"],
                "title": f"[sw] phase:{uid}:{p['id']}",
                "slug": p.get("slug", ""),
            }
            for p in phases
        ]
    result["plan"] = plan
    result["checkboxBlock"] = checkbox_block

    if dry_run:
        result["projection"] = {"kind": mode_info["mode"], "plan": plan}
        return result
    issue_store = resolve_effective_backend(worktree, cfg).get("effective") == "issue-store"
    client = IssuesClient(worktree, provider)
    epic_body = compose_issue_body(project_key, "tasks", uid, checkbox_block)
    epic = client.issue_create(
        title=plan["epic"]["title"],
        body=epic_body,
        labels=sorted({project_label(project_key), type_label("tasks"), "sw:visibility:public"}),
        project_key=project_key,
        artifact_type="tasks",
        unit_id=uid,
    )
    if issue_store:
        index = load_issue_unit_index(worktree)
        index[issue_index_key(project_key, uid)] = epic.id
        save_issue_unit_index(worktree, index)
    sub_refs: list[dict[str, Any]] = []
    if mode_info["mode"] == "epic-sub-issue":
        for sub in plan["subIssues"]:
            phase_unit_id = f"{uid}-phase-{sub['phaseId']}"
            phase_body = compose_issue_body(
                project_key,
                "tasks",
                phase_unit_id,
                f"Phase {sub['phaseId']}: {sub['title']}\n",
                edges=[{"rel": "sub-issue-of", "target": uid}] if issue_store else None,
            )
            native_links: list[dict[str, Any]] | None = None
            if issue_store:
                index = load_issue_unit_index(worktree)
                native_links = native_links_from_edges(
                    [{"rel": "sub-issue-of", "target": uid}],
                    index,
                    project_key=project_key,
                ) or None
            child = client.issue_create(
                title=sub["title"],
                body=phase_body,
                labels=sorted({project_label(project_key), type_label("tasks"), f"sw:phase:{sub['phaseId']}"}),
                project_key=project_key,
                artifact_type="tasks",
                unit_id=phase_unit_id,
                native_links=native_links,
            )
            if issue_store:
                index = load_issue_unit_index(worktree)
                index[issue_index_key(project_key, phase_unit_id)] = child.id
                save_issue_unit_index(worktree, index)
            sub_refs.append({"phaseId": sub["phaseId"], "issueId": child.id, "number": child.number})
    result["epicIssueId"] = epic.id
    result["subIssues"] = sub_refs
    result["projection"] = {
        "kind": mode_info["mode"],
        "epicIssueId": epic.id,
        "subIssues": sub_refs,
        "phases": phases,
    }
    return result


def _cmd_matrix(_args: argparse.Namespace) -> int:
    print(json.dumps({"verdict": "ok", "matrix": hierarchy_capability_matrix()}, indent=2))
    return 0


def _cmd_resolve_mode(args: argparse.Namespace) -> int:
    provider = args.provider or _issues_provider(Path(args.root))
    print(json.dumps(resolve_hierarchy_mode(provider), indent=2))
    return 0


def _cmd_aggregate_status(args: argparse.Namespace) -> int:
    payload = json.loads(args.payload_json)
    result = aggregate_parent_status(payload["parent"], list(payload.get("children") or []))
    print(json.dumps(result, indent=2))
    return 0 if result.get("verdict") == "ok" else 20


def _cmd_project(args: argparse.Namespace) -> int:
    result = project_task_list_hierarchy(
        Path(args.root),
        Path(args.task_list),
        unit_id=args.unit_id,
        dry_run=not args.apply,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("verdict") == "ok" else 20


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PRD 046 planning hierarchy")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    p_matrix = sub.add_parser("matrix", help="Hierarchy capability matrix (R94)")
    p_matrix.set_defaults(func=_cmd_matrix)

    p_mode = sub.add_parser("resolve-mode", help="Resolve epic-sub-issue vs checkbox mode")
    p_mode.add_argument("--provider", default=None)
    p_mode.set_defaults(func=_cmd_resolve_mode)

    p_agg = sub.add_parser("aggregate-status", help="Aggregate parent status from children (R91)")
    p_agg.add_argument("--payload-json", required=True)
    p_agg.set_defaults(func=_cmd_aggregate_status)

    p_proj = sub.add_parser("project", help="Project task list hierarchy")
    p_proj.add_argument("task_list", help="Path to frozen task list")
    p_proj.add_argument("--unit-id", default=None)
    p_proj.add_argument("--apply", action="store_true", help="Create issues (non-dry-run)")
    p_proj.set_defaults(func=_cmd_project)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
