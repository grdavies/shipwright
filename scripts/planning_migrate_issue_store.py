#!/usr/bin/env python3
"""PRD 044 Phase 1+2 — issue-store migration engine (dry-run default, journaled, lifecycle-aware)."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from urllib.parse import quote, unquote
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_FM_FIELD = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
_EDGE_FM_KEYS = {
    "depends": "depends",
    "blocks": "blocks",
    "supersedes": "supersedes",
    "extends": "extends",
    "absorbs": "absorbs",
    "prd": "prd",
    "amends": "amends",
    "brainstorm": "brainstorm",
}
_EDGE_INVERSE_REL = {
    "blocks": "depends",
    "depends": "blocks",
}
_GAP_STATUS_LABELS = frozenset({"open", "gap-scheduled", "resolved", "sw:gap-open", "sw:gap-scheduled", "sw:gap-resolved"})
_GAP_SCHEDULE_LABEL_PREFIX = "sw:gap-schedule:"
_FROZEN_AT_LABEL_PREFIX = "sw:frozen-at:"
_VISIBILITY_LABEL_PREFIX = "sw:visibility:"
_STATUS_LABEL_PREFIX = "sw:status:"



def _encode_gap_schedule_for_label(schedule: str) -> str:
    """Jira labels cannot contain spaces; percent-encode schedule payload."""
    return quote(schedule, safe="")


def _decode_gap_schedule_from_label(suffix: str) -> str:
    return unquote(suffix)


def parse_frontmatter_fields(content: str) -> dict[str, str]:
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end == -1:
        return {}
    block = content[3:end]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        match = _FM_FIELD.match(line.strip())
        if match:
            fields[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    return fields


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_lib import load_workflow_config  # noqa: E402
from issues_lib import IssueNotFound, IssueRevisionConflict, IssuesClient  # noqa: E402
from planning_artifact_handle import issue_store_separate_project_effective  # noqa: E402
from planning_canonical import (  # noqa: E402
    FROZEN_LABEL,
    IssueSnapshot,
    build_edges_block,
    build_freeze_record_body,
    canonical_hash,
    chunk_body_if_needed,
    compose_issue_body,
    gap_status_from_labels,
    gap_status_label,
    infer_artifact_type,
    native_links_from_edges,
    normalize_body,
    parse_edges_block,
    parse_freeze_record_hash,
    project_label,
    reassemble_body,
    slugify,
    status_from_labels,
    status_label,
    strip_markers_and_edges,
    title_prefix,
    type_label,
)
from planning_jira_canonical import chunk_body_for_jira_cloud, jira_markdown_canonical, rewrite_chunk_manifest  # noqa: E402
from planning_store import (  # noqa: E402
    InRepoPublicBackend,
    IssueStoreBackend,
    content_hash,
    issue_index_key,
    issue_store_visibility_gate,
    load_issue_unit_index,
    parse_visibility_from_content,
    save_issue_unit_index,
    secret_scan_text,
    validate_project_key,
)

JOURNAL_REL = ".cursor/hooks/state/issue-store-migration-journal.json"
ISSUE_STORE_LOCK_REL = ".cursor/hooks/state/issue-store-migration.lock"
TRANSITION_STAMP_REL = ".cursor/hooks/state/issue-store-migration-transition.json"
GAP_BACKLOG_SHIM_MARKER = "<!-- issue-store-migration-gap-shim: generated v1 -->"
DIRECTION_FILES_TO_ISSUES = "files-to-issues"
DIRECTION_ISSUES_TO_FILES = "issues-to-files"
DIRECTIONS = frozenset({DIRECTION_FILES_TO_ISSUES, DIRECTION_ISSUES_TO_FILES})

ARTIFACT_STATES = ("pending", "created", "verified", "source-removed")
SKIP_BASENAMES = frozenset(
    {
        "INDEX.md",
        "INDEX-archive.md",
        "SUPERSEDED.md",
        "COMPLETION-LOG.md",
        "GAP-BACKLOG.md",
        "FEEDBACK-CHECKLIST.md",
    }
)
WALK_ROOTS = ("docs/planning", "docs/prds", "docs/brainstorms", "docs/decisions")


@dataclass(frozen=True)
class ArtifactLifecycle:
    issue_state: str
    frozen: bool
    freeze_hash: str | None
    frozen_at: str | None
    edge_list: list[dict[str, Any]] = field(default_factory=list)
    native_links: list[dict[str, Any]] = field(default_factory=list)
    gap_status: str | None = None
    gap_schedule: str | None = None
    visibility: str | None = None
    consumer_status: str | None = None


@dataclass(frozen=True)
class MigrationArtifact:
    source_path: str
    body_path: str
    unit_id: str
    content: str
    digest: str
    artifact_type: str
    lifecycle: ArtifactLifecycle
    issue_id: str | None = None
    title: str | None = None


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def journal_path(root: Path) -> Path:
    return root / JOURNAL_REL


def idempotency_key(source_path: str, digest: str) -> str:
    return f"{source_path}:{digest}"


def load_journal(root: Path) -> dict[str, Any]:
    path = journal_path(root)
    if not path.is_file():
        return {"version": 1, "direction": None, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        fail("journal-corrupt", path=JOURNAL_REL)
    if not isinstance(data, dict):
        fail("journal-invalid", path=JOURNAL_REL)
    data.setdefault("version", 1)
    data.setdefault("entries", {})
    if not isinstance(data["entries"], dict):
        fail("journal-invalid-entries", path=JOURNAL_REL)
    return data


def save_journal(root: Path, journal: dict[str, Any], *, apply: bool) -> None:
    if not apply:
        return
    path = journal_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(journal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")



def transition_stamp_path(root: Path) -> Path:
    return root / TRANSITION_STAMP_REL


def issue_store_lock_path(root: Path) -> Path:
    return root / ISSUE_STORE_LOCK_REL


def write_transition_stamp(root: Path, journal: dict[str, Any], *, apply: bool) -> None:
    if not apply:
        return
    incomplete = journal_incomplete_keys(journal)
    path = transition_stamp_path(root)
    if incomplete:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "direction": journal.get("direction"),
                    "incompleteCount": len(incomplete),
                    "updatedAt": time.time(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    elif path.is_file():
        path.unlink()


def journal_incomplete_keys(journal: dict[str, Any]) -> list[str]:
    entries = journal.get("entries", {})
    if not isinstance(entries, dict):
        return []
    return [
        key
        for key, entry in entries.items()
        if isinstance(entry, dict) and entry.get("state") != "source-removed"
    ]


def migration_in_transition(root: Path) -> bool:
    journal = load_journal(root)
    if journal.get("direction") and journal_incomplete_keys(journal):
        return True
    return transition_stamp_path(root).is_file()


def issue_store_effective(root: Path, cfg: dict[str, Any] | None = None) -> bool:
    from planning_store import resolve_effective_backend

    cfg = cfg or load_workflow_config(root)
    effective = resolve_effective_backend(root, cfg)
    return str(effective.get("effective", "")) == "issue-store"


def issue_store_separate_project(root: Path, cfg: dict[str, Any] | None = None) -> bool:
    """Shared R1-R4 guard predicate: issue-store effective AND ``storeLocation.mode``
    (via ``resolve_store_location``) is ``separate-project`` (PRD 057 R1).

    Single source of truth for the pollution/currency guards across this wave —
    gap-backlog write-through here (R1); spec-seed INDEX guard (R2), reconcile
    derived-artifact guard (R3), and gap-resolution store close (R4) reuse it in
    later phases — so ``same-repo`` deployments keep retaining local writes and
    only ``separate-project`` deployments skip them.
    """
    return issue_store_separate_project_effective(root, cfg)


def project_native_links_from_edges(
    root: Path,
    edge_list: list[dict[str, Any]],
    explicit_native: list[dict[str, Any]],
    project_key: str,
) -> list[dict[str, Any]]:
    """Project sw-edges to provider native links via the issue unit index."""
    index = load_issue_unit_index(root)
    projected = native_links_from_edges(edge_list, index, project_key=project_key)
    out = list(projected)
    for link in explicit_native:
        if isinstance(link, dict) and link not in out:
            out.append(link)
    return out


def resolved_native_links_for_edges(
    root: Path,
    cfg: dict[str, Any],
    edge_list: list[dict[str, Any]],
    explicit_native: list[dict[str, Any]],
    project_key: str,
) -> list[dict[str, Any]]:
    """Project sw-edges to provider native links when issue-store is effective (PRD 056 R4)."""
    if not issue_store_effective(root, cfg):
        return list(explicit_native)
    return project_native_links_from_edges(root, edge_list, explicit_native, project_key)


def sync_issue_native_links_from_content(
    root: Path,
    unit_id: str,
    content: str,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Sync provider native links from sw-edges on an existing issue (gap/hierarchy writes)."""
    cfg = cfg or load_workflow_config(root)
    if not issue_store_effective(root, cfg):
        return {"skipped": True, "reason": "not-issue-store"}
    key_result = validate_project_key(root, cfg)
    if key_result.get("verdict") != "ok":
        return {"skipped": True, "reason": "invalid-project-key"}
    project_key = str(key_result["projectKey"])
    edges_data = parse_edges_block(normalize_body(content)) or {}
    edge_list = list(edges_data.get("edges") or [])
    explicit_native = list(edges_data.get("native") or [])
    native_links = resolved_native_links_for_edges(
        root, cfg, edge_list, explicit_native, project_key
    )
    if not native_links:
        return {"skipped": True, "reason": "no-native-links"}
    client = cfg_issues_client(root)
    idx_key = issue_index_key(project_key, unit_id)
    issue_id = load_issue_unit_index(root).get(idx_key)
    record = None
    if issue_id:
        try:
            record = client.issue_get(str(issue_id))
        except IssueNotFound:
            record = None
    if record is None:
        matches = client.issue_search(project_key=project_key, unit_id=unit_id)
        if not matches:
            return {"skipped": True, "reason": "issue-missing", "unitId": unit_id}
        record = matches[0]
    updated = client.issue_update(
        record.id,
        native_links=native_links,
        if_match=record.etag,
    )
    return {"unitId": unit_id, "issueId": updated.id, "nativeLinks": native_links}


def gap_backlog_is_readonly(root: Path) -> bool:
    if migration_in_transition(root):
        return True
    cfg = load_workflow_config(root)
    # PRD 057 R1: only separate-project makes the legacy row read-only —
    # same-repo issue-store deployments retain local GAP-BACKLOG.md writes.
    if issue_store_separate_project(root, cfg):
        return True
    dirs = pp_load_planning_dirs(root)
    gap_path = root / dirs.prds / "GAP-BACKLOG.md"
    if not gap_path.is_file():
        return False
    return GAP_BACKLOG_SHIM_MARKER in gap_path.read_text(encoding="utf-8")


def is_gap_projection_content(content: str) -> bool:
    return GAP_BACKLOG_SHIM_MARKER in content


def _gap_title_from_record(record: Any) -> str:
    title = str(getattr(record, "title", "") or "")
    prefix = title_prefix(str(getattr(record, "project_key", "") or ""))
    artifact = f" gap:{getattr(record, 'unit_id', '')}"
    if title.startswith(prefix) and artifact in title:
        return title.split(artifact, 1)[-1].strip() or getattr(record, "unit_id", "")
    return title or str(getattr(record, "unit_id", ""))


def _gap_table_status_from_lifecycle(lifecycle: ArtifactLifecycle) -> str:
    return _gap_status_label(lifecycle)


def list_gap_issue_records(root: Path, cfg: dict[str, Any] | None = None) -> list[Any]:
    cfg = cfg or load_workflow_config(root)
    key_result = validate_project_key(root, cfg)
    if key_result.get("verdict") != "ok":
        return []
    project_key = str(key_result["projectKey"])
    client = cfg_issues_client(root)
    return client.issue_search(project_key=project_key, artifact_type="gap")


def render_gap_backlog_from_issue_records(records: list[Any]) -> str:
    lines = [
        GAP_BACKLOG_SHIM_MARKER,
        "",
        "Read-only issue-derived projection (PRD 045 R21/R72).",
        "Edit canonical gap issues — not this file.",
        "",
        "| ID | Status | Title |",
        "|----|--------|-------|",
    ]
    for record in sorted(records, key=lambda item: str(getattr(item, "unit_id", ""))):
        lifecycle = extract_lifecycle_from_record(record)
        gid = _gap_legacy_id(str(getattr(record, "unit_id", "")))
        status = _gap_table_status_from_lifecycle(lifecycle)
        title = _gap_title_from_record(record)
        lines.append(f"| {gid} | {status} | {title} |")
    lines.append("")
    return "\n".join(lines)


def parse_gap_backlog_projection_rows(content: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in content.splitlines():
        if not line.startswith("| GAP-"):
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) < 3:
            continue
        rows.append({"gapId": parts[0].upper(), "status": parts[1].lower(), "title": parts[2]})
    return rows


def expected_gap_backlog_rows_from_issues(root: Path, cfg: dict[str, Any] | None = None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for record in list_gap_issue_records(root, cfg):
        lifecycle = extract_lifecycle_from_record(record)
        rows.append(
            {
                "gapId": _gap_legacy_id(str(record.unit_id)),
                "status": _gap_table_status_from_lifecycle(lifecycle),
                "title": _gap_title_from_record(record),
            }
        )
    rows.sort(key=lambda row: row["gapId"])
    return rows


def diagnose_gap_projection_divergence(root: Path, cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    cfg = cfg or load_workflow_config(root)
    if not issue_store_effective(root, cfg):
        return []
    dirs = pp_load_planning_dirs(root)
    gap_path = root / dirs.prds / "GAP-BACKLOG.md"
    if not gap_path.is_file():
        expected = expected_gap_backlog_rows_from_issues(root, cfg)
        if expected:
            return [
                {
                    "kind": "projection-missing",
                    "expectedRows": len(expected),
                    "repair": "refresh-gap-backlog-projection",
                }
            ]
        return []
    content = gap_path.read_text(encoding="utf-8")
    if not is_gap_projection_content(content):
        return []
    expected = expected_gap_backlog_rows_from_issues(root, cfg)
    actual = parse_gap_backlog_projection_rows(content)
    issues: list[dict[str, Any]] = []
    expected_by_id = {row["gapId"]: row for row in expected}
    actual_by_id = {row["gapId"]: row for row in actual}
    for gap_id, row in expected_by_id.items():
        other = actual_by_id.get(gap_id)
        if not other:
            issues.append({"kind": "projection-row-missing", "gapId": gap_id, "expected": row})
            continue
        if other["status"] != row["status"]:
            issues.append(
                {
                    "kind": "projection-status-mismatch",
                    "gapId": gap_id,
                    "expectedStatus": row["status"],
                    "actualStatus": other["status"],
                }
            )
    for gap_id in sorted(set(actual_by_id) - set(expected_by_id)):
        issues.append({"kind": "projection-row-stale", "gapId": gap_id, "actual": actual_by_id[gap_id]})
    return issues


def count_file_native_open_gaps(root: Path) -> int:
    import planning_index_gen as pig

    open_count = 0
    for unit in pig.discover_units(root):
        if unit.type != "gap":
            continue
        body = root / unit.body_path
        if not body.is_file():
            continue
        lifecycle = extract_lifecycle_from_file(body.read_text(encoding="utf-8"), "gap")
        if _gap_table_status_from_lifecycle(lifecycle) == "open":
            open_count += 1
    return open_count


GAP_BACKLOG_SUNSET_STUB_MARKER = "<!-- issue-store-gap-backlog-sunset: v1 -->"


def render_gap_backlog_sunset_stub() -> str:
    """Documented sunset stub for GAP-BACKLOG.md under issue-store separate-project
    once no open gaps remain (PRD 057 R1). Replaces outright file removal so a path
    still referenced by docs/tooling resolves to an explanation instead of a 404."""
    return (
        "\n".join(
            [
                GAP_BACKLOG_SUNSET_STUB_MARKER,
                "",
                "# GAP-BACKLOG (sunset)",
                "",
                "This local projection is retired under issue-store `separate-project` "
                "(PRD 057 R1). Gap units are captured and resolved directly in the "
                "planning-project issue store; no open gaps remain to project locally. "
                "See `core/skills/feedback/SKILL.md` for the store-only capture contract.",
                "",
            ]
        )
        + "\n"
    )


def refresh_gap_backlog_projection(
    root: Path,
    cfg: dict[str, Any] | None = None,
    *,
    apply: bool = True,
    projection: bool = False,
) -> dict[str, Any]:
    cfg = cfg or load_workflow_config(root)
    if migration_in_transition(root):
        return refresh_gap_backlog_shim(root, cfg, apply=apply)
    if not issue_store_effective(root, cfg):
        return {"skipped": True, "reason": "not-issue-store"}
    dirs = pp_load_planning_dirs(root)
    gap_path = root / dirs.prds / "GAP-BACKLOG.md"
    if issue_store_separate_project(root, cfg) and not projection:
        # PRD 057 R1: gap capture already writes through to the issue store under
        # separate-project; skip the legacy local projection write unless the
        # operator explicitly retains it via --projection.
        return {
            "gapBacklog": str(gap_path.relative_to(root)),
            "readonly": True,
            "source": "issue-derived",
            "skipped": True,
            "reason": "separate-project-write-through",
        }
    records = list_gap_issue_records(root, cfg)
    content = render_gap_backlog_from_issue_records(records)
    if apply:
        gap_path.parent.mkdir(parents=True, exist_ok=True)
        gap_path.write_text(content, encoding="utf-8")
    return {
        "gapBacklog": str(gap_path.relative_to(root)),
        "gapRows": len(records),
        "readonly": True,
        "source": "issue-derived",
    }


def try_sunset_gap_backlog_projection(
    root: Path, cfg: dict[str, Any] | None = None, *, apply: bool = True
) -> dict[str, Any]:
    cfg = cfg or load_workflow_config(root)
    if not issue_store_effective(root, cfg):
        return {"skipped": True, "reason": "not-issue-store"}
    if migration_in_transition(root):
        return {"skipped": True, "reason": "migration-in-transition"}
    if count_file_native_open_gaps(root) > 0:
        return {"skipped": True, "reason": "file-native-open-gaps-remain"}
    if list_gap_issue_records(root, cfg):
        return {"skipped": True, "reason": "gap-issues-remain"}
    dirs = pp_load_planning_dirs(root)
    gap_path = root / dirs.prds / "GAP-BACKLOG.md"
    # PRD 057 R1: same-repo keeps removing the generated projection outright;
    # separate-project reduces it to a documented sunset stub instead.
    separate_project = issue_store_separate_project(root, cfg)
    if not gap_path.is_file():
        if not separate_project:
            return {"removed": False, "reason": "no-projection"}
        if apply:
            gap_path.parent.mkdir(parents=True, exist_ok=True)
            gap_path.write_text(render_gap_backlog_sunset_stub(), encoding="utf-8")
        return {"removed": False, "stubbed": True, "gapBacklog": str(gap_path.relative_to(root))}
    content = gap_path.read_text(encoding="utf-8")
    if GAP_BACKLOG_SUNSET_STUB_MARKER in content:
        return {"removed": False, "stubbed": True, "reason": "already-sunset-stub"}
    if not is_gap_projection_content(content):
        return {"removed": False, "reason": "not-generated-projection"}
    if separate_project:
        if apply:
            gap_path.write_text(render_gap_backlog_sunset_stub(), encoding="utf-8")
        return {"removed": False, "stubbed": True, "gapBacklog": str(gap_path.relative_to(root))}
    if apply:
        gap_path.unlink()
    return {"removed": True, "gapBacklog": str(gap_path.relative_to(root))}


def sync_gap_issue_labels(root: Path, unit_id: str, content: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_workflow_config(root)
    if not issue_store_effective(root, cfg):
        return {"skipped": True, "reason": "not-issue-store"}
    key_result = validate_project_key(root, cfg)
    if key_result.get("verdict") != "ok":
        fail(key_result.get("message") or key_result.get("error", "invalid-project-key"))
    project_key = str(key_result["projectKey"])
    client = cfg_issues_client(root)
    record = None
    idx_key = issue_index_key(project_key, unit_id)
    issue_id = load_issue_unit_index(root).get(idx_key)
    if issue_id:
        try:
            record = client.issue_get(str(issue_id))
        except IssueNotFound:
            record = None
    if record is None:
        matches = client.issue_search(project_key=project_key, unit_id=unit_id, artifact_type="gap")
        if not matches:
            fail("gap-issue-missing", unitId=unit_id)
        record = matches[0]
    lifecycle = extract_lifecycle_from_file(content, "gap")
    labels = _apply_gap_labels(list(record.labels), lifecycle, "gap")
    updated = client.issue_update(record.id, labels=labels, if_match=record.etag)
    return {"unitId": unit_id, "issueId": updated.id, "labels": labels}


def gap_unit_ids_scheduled_for_prd(root: Path, prd: str, cfg: dict[str, Any] | None = None) -> list[str]:
    """Gap issue unit ids scheduled for ``prd`` under issue-store (PRD 057 R4).

    Mirrors ``gap_backlog.flip_resolve``'s schedule-label matching so
    ``gap_backlog.resolve_for_prd`` can locate the gap issues an absorbing PRD
    should close when there is no local canonical gap file to inspect
    (issue-store ``separate-project``).
    """
    cfg = cfg or load_workflow_config(root)
    prd_n = str(int(prd)) if prd.isdigit() else prd.lstrip("0") or prd
    sched_re = re.compile(
        rf"^PRD\s+0*{re.escape(str(int(prd_n))) if prd_n.isdigit() else re.escape(prd_n)}(?:\s+A\d+)?$",
        re.I,
    )
    unit_ids: list[str] = []
    for record in list_gap_issue_records(root, cfg):
        schedule = _gap_schedule_from_labels(list(getattr(record, "labels", [])))
        if schedule and sched_re.match(schedule.strip()):
            unit_ids.append(str(getattr(record, "unit_id", "")))
    return unit_ids


def close_gap_issue(root: Path, unit_id: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Close the gap issue for ``unit_id`` and apply the resolved label idempotently
    (PRD 057 R4).

    Shared by ``gap_backlog.resolve_for_prd`` (in turn used by both
    ``reconcile_lib.set_index_status`` and the standalone ``gap-backlog.py flip
    --resolve`` CLI) under issue-store ``separate-project`` — the issue is the
    sole resolution record there, so this replaces the local frontmatter/row edit
    that ``same-repo`` keeps. Returns ``{"verdict": "resolution-partial", ...}``
    (never raises) on any lookup or update failure so callers can aggregate
    partial outcomes across multiple gap units without losing already-applied
    progress.
    """
    cfg = cfg or load_workflow_config(root)
    if not issue_store_effective(root, cfg):
        return {"verdict": "pass", "skipped": True, "reason": "not-issue-store", "unitId": unit_id}
    key_result = validate_project_key(root, cfg)
    if key_result.get("verdict") != "ok":
        return {
            "verdict": "resolution-partial",
            "unitId": unit_id,
            "error": key_result.get("message") or key_result.get("error", "invalid-project-key"),
        }
    project_key = str(key_result["projectKey"])
    client = cfg_issues_client(root)
    record = None
    idx_key = issue_index_key(project_key, unit_id)
    issue_id = load_issue_unit_index(root).get(idx_key)
    if issue_id:
        try:
            record = client.issue_get(str(issue_id))
        except IssueNotFound:
            record = None
    if record is None:
        matches = client.issue_search(project_key=project_key, unit_id=unit_id, artifact_type="gap")
        if not matches:
            return {"verdict": "resolution-partial", "unitId": unit_id, "error": "gap-issue-missing"}
        record = matches[0]
    lifecycle = ArtifactLifecycle(
        issue_state="closed",
        frozen=False,
        freeze_hash=None,
        frozen_at=None,
        gap_status="resolved",
    )
    labels = _apply_gap_labels(list(record.labels), lifecycle, "gap")
    if record.state == "closed" and set(labels) == set(record.labels):
        return {"verdict": "pass", "unitId": unit_id, "issueId": record.id, "labels": labels, "alreadyClosed": True}
    try:
        updated = client.issue_update(record.id, labels=labels, state="closed", if_match=record.etag)
    except Exception as exc:  # noqa: BLE001 — any close/label failure is a resolution-partial finding, not a crash
        return {"verdict": "resolution-partial", "unitId": unit_id, "error": str(exc), "labels": labels}
    return {"verdict": "pass", "unitId": unit_id, "issueId": updated.id, "labels": labels}


def pp_load_planning_dirs(root: Path) -> Any:
    import planning_paths as pp

    return pp.load_planning_dirs(root)


def scan_quiesce_blockers(root: Path) -> list[dict[str, Any]]:
    from planning_migrate import scan_runstate
    from wave_living_doc_lock import lock_path as living_lock_path
    from wave_state import lock_is_stale, lock_owner_live, read_lock_meta

    blockers: list[dict[str, Any]] = list(scan_runstate(root))
    living = living_lock_path(root)
    if living.is_file():
        meta = read_lock_meta(living)
        if not lock_is_stale(living) and lock_owner_live(meta):
            blockers.append(
                {
                    "kind": "reconcile",
                    "path": str(living.relative_to(root)).replace("\\", "/"),
                    "holder": meta,
                }
            )
    lock = issue_store_lock_path(root)
    if lock.is_file():
        try:
            held = json.loads(lock.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            held = {}
        if held.get("pid") != os.getpid():
            blockers.append(
                {
                    "kind": "issue-store-migration-lock",
                    "path": ISSUE_STORE_LOCK_REL,
                    "holder": held,
                }
            )
    return blockers


def assert_quiesced(root: Path) -> None:
    blockers = scan_quiesce_blockers(root)
    if blockers:
        fail(
            "quiesce-required",
            exit_code=20,
            blockers=blockers,
            remediation="wait for active deliver runs and reconciler to finish before migrating",
        )


def acquire_issue_store_lock(root: Path) -> None:
    path = issue_store_lock_path(root)
    if path.is_file():
        fail("issue-store-migration-lock-held", exit_code=20, lock=ISSUE_STORE_LOCK_REL)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "heldAt": time.time(),
        "pid": os.getpid(),
        "host": os.uname().nodename,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def release_issue_store_lock(root: Path) -> None:
    issue_store_lock_path(root).unlink(missing_ok=True)


def _source_exists(root: Path, direction: str, artifact: MigrationArtifact) -> bool:
    if direction == DIRECTION_FILES_TO_ISSUES:
        return (root / artifact.source_path).is_file()
    if artifact.issue_id:
        try:
            cfg_issues_client(root).issue_get(artifact.issue_id)
            return True
        except IssueNotFound:
            return False
    return False


def _gap_legacy_id(unit_id: str) -> str:
    m = re.match(r"^gap-(\d+)-", unit_id)
    if m:
        return f"GAP-{m.group(1)}"
    return unit_id.upper()


def _gap_status_label(lifecycle: ArtifactLifecycle) -> str:
    if lifecycle.gap_status:
        lowered = lifecycle.gap_status.lower()
        if lowered in {"planned", "scheduled"}:
            return "scheduled"
        if lowered == "resolved":
            return "resolved"
        return "open"
    return "open"


def refresh_gap_backlog_shim(root: Path, cfg: dict[str, Any] | None = None, *, apply: bool = True) -> dict[str, Any]:
    if not migration_in_transition(root):
        return {"skipped": True, "reason": "not-in-transition"}
    cfg = cfg or load_workflow_config(root)
    dirs = pp_load_planning_dirs(root)
    direction = str(load_journal(root).get("direction") or DIRECTION_FILES_TO_ISSUES)
    gaps = [a for a in discover_artifacts(root, direction, cfg) if a.artifact_type == "gap"]
    lines = [
        GAP_BACKLOG_SHIM_MARKER,
        "",
        "Read-only projection during issue-store migration (PRD 044 R38).",
        "Edit canonical gap units or issues — not this file.",
        "",
        "| ID | Status | Title |",
        "|----|--------|-------|",
    ]
    for gap in sorted(gaps, key=lambda a: a.unit_id):
        gid = _gap_legacy_id(gap.unit_id)
        status = _gap_status_label(gap.lifecycle)
        title = gap.title or gap.unit_id
        lines.append(f"| {gid} | {status} | {title} |")
    lines.append("")
    content = "\n".join(lines)
    gap_path = root / dirs.prds / "GAP-BACKLOG.md"
    if apply:
        gap_path.parent.mkdir(parents=True, exist_ok=True)
        gap_path.write_text(content, encoding="utf-8")
    return {
        "gapBacklog": str(gap_path.relative_to(root)),
        "gapRows": len(gaps),
        "readonly": True,
    }


def remove_gap_backlog_shim(root: Path, *, apply: bool = True) -> dict[str, Any]:
    dirs = pp_load_planning_dirs(root)
    gap_path = root / dirs.prds / "GAP-BACKLOG.md"
    stamp = transition_stamp_path(root)
    removed = False
    if apply:
        if gap_path.is_file() and GAP_BACKLOG_SHIM_MARKER in gap_path.read_text(encoding="utf-8"):
            gap_path.unlink()
            removed = True
        if stamp.is_file():
            stamp.unlink()
    return {"removed": removed, "gapBacklog": str(gap_path.relative_to(root))}


def diagnose_migration(root: Path, direction: str, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    journal = load_journal(root)
    file_backend = InRepoPublicBackend(root, cfg)
    issue_backend = IssueStoreBackend(root, cfg)
    issues: list[dict[str, Any]] = []
    for artifact in discover_artifacts(root, direction, cfg):
        entry = _journal_entry(journal, artifact)
        state = str(entry.get("state", "pending"))
        source_present = _source_exists(root, direction, artifact)
        target_ok = _verify_target(
            root, direction, artifact, file_backend, issue_backend, cfg, apply=True
        )
        if state == "created" and not target_ok:
            issues.append(
                {
                    "kind": "created-but-unverified",
                    "unitId": artifact.unit_id,
                    "sourcePath": artifact.source_path,
                    "repair": "rollback-target",
                }
            )
        elif state == "created" and target_ok:
            issues.append(
                {
                    "kind": "created-ready-to-verify",
                    "unitId": artifact.unit_id,
                    "sourcePath": artifact.source_path,
                    "repair": "advance-to-verified",
                }
            )
        elif state in {"verified", "source-removed"} and source_present:
            issues.append(
                {
                    "kind": "verified-but-source-present",
                    "unitId": artifact.unit_id,
                    "sourcePath": artifact.source_path,
                    "state": state,
                    "repair": "complete-source-removal" if target_ok else "rollback-target",
                }
            )
        elif state == "pending" and target_ok and not source_present:
            issues.append(
                {
                    "kind": "target-without-journal",
                    "unitId": artifact.unit_id,
                    "sourcePath": artifact.source_path,
                    "repair": "advance-journal",
                }
            )
    return issues


def repair_migration_issue(
    root: Path,
    cfg: dict[str, Any],
    direction: str,
    issue: dict[str, Any],
    journal: dict[str, Any],
    file_backend: InRepoPublicBackend,
    issue_backend: IssueStoreBackend,
    *,
    apply: bool,
) -> dict[str, Any]:
    unit_id = str(issue.get("unitId", ""))
    artifacts = [a for a in discover_artifacts(root, direction, cfg) if a.unit_id == unit_id]
    if not artifacts:
        return {"unitId": unit_id, "action": "skip", "reason": "artifact-missing"}
    artifact = artifacts[0]
    entry = _journal_entry(journal, artifact)
    repair = str(issue.get("repair", ""))
    if repair == "advance-to-verified":
        entry["state"] = "verified"
        _set_entry(journal, artifact, entry)
        save_journal(root, journal, apply=apply)
        return {"unitId": unit_id, "action": "advance-to-verified"}
    if repair == "complete-source-removal" and apply:
        _remove_source(root, direction, artifact, apply=True)
        entry["state"] = "source-removed"
        _set_entry(journal, artifact, entry)
        save_journal(root, journal, apply=apply)
        return {"unitId": unit_id, "action": "complete-source-removal"}
    if repair == "rollback-target" and apply:
        if direction == DIRECTION_FILES_TO_ISSUES:
            provider = str(cfg.get("planning", {}).get("store", {}).get("issuesProvider", "none"))
            client = IssuesClient(root, provider)
            try:
                record = _lookup_issue_record(
                    root,
                    issue_backend.project_key,
                    artifact.unit_id,
                    artifact.body_path,
                    client,
                )
                client.mark_tombstone(record.id)
            except IssueNotFound:
                pass
        else:
            path = root / artifact.body_path
            if path.is_file():
                path.unlink()
        entry["state"] = "pending"
        entry.pop("targetRef", None)
        _set_entry(journal, artifact, entry)
        save_journal(root, journal, apply=apply)
        return {"unitId": unit_id, "action": "rollback-target"}
    if repair == "advance-journal":
        entry["state"] = "source-removed"
        _set_entry(journal, artifact, entry)
        save_journal(root, journal, apply=apply)
        return {"unitId": unit_id, "action": "advance-journal"}
    return {"unitId": unit_id, "action": "noop", "repair": repair}


ROLLBACK_INVARIANTS = [
    "Rollback removes unverified targets and resets journal entries to pending.",
    "Verified targets with sources still present complete source removal when repair applies.",
    "source-removed entries are terminal — rollback recreates sources from verified targets only via doctor repair.",
    "After rollback or repair, every artifact has either a verified target or its source — never neither.",
]


def run_store_doctor(root: Path, *, apply: bool = False) -> None:
    root = root.resolve()
    cfg = load_workflow_config(root)
    journal = load_journal(root)
    direction = str(journal.get("direction") or DIRECTION_FILES_TO_ISSUES)
    if direction not in DIRECTIONS:
        fail("invalid-direction", direction=direction)
    issues = diagnose_migration(root, direction, cfg)
    repairs: list[dict[str, Any]] = []
    if apply and issues:
        file_backend = InRepoPublicBackend(root, cfg)
        issue_backend = IssueStoreBackend(root, cfg)
        for issue in issues:
            repairs.append(
                repair_migration_issue(
                    root,
                    cfg,
                    direction,
                    issue,
                    journal,
                    file_backend,
                    issue_backend,
                    apply=True,
                )
            )
            journal = load_journal(root)
        write_transition_stamp(root, journal, apply=True)
        refresh_gap_backlog_shim(root, cfg, apply=True)
    emit(
        {
            "verdict": "pass",
            "mode": "apply" if apply else "dry-run",
            "action": "store-doctor",
            "direction": direction,
            "issueCount": len(issues),
            "issues": issues,
            "repairs": repairs,
            "rollbackInvariants": ROLLBACK_INVARIANTS,
        }
    )


def rollback_store_migration(root: Path, *, apply: bool = False) -> None:
    root = root.resolve()
    assert_quiesced(root)
    cfg = load_workflow_config(root)
    journal = load_journal(root)
    direction = str(journal.get("direction") or DIRECTION_FILES_TO_ISSUES)
    if direction not in DIRECTIONS:
        fail("invalid-direction", direction=direction)
    issues = [
        issue
        for issue in diagnose_migration(root, direction, cfg)
        if issue.get("kind")
        in {"created-but-unverified", "verified-but-source-present", "target-without-journal"}
    ]
    repairs: list[dict[str, Any]] = []
    if apply:
        acquire_issue_store_lock(root)
        try:
            file_backend = InRepoPublicBackend(root, cfg)
            issue_backend = IssueStoreBackend(root, cfg)
            for issue in issues:
                mutated = dict(issue)
                if issue.get("kind") == "verified-but-source-present":
                    mutated["repair"] = "rollback-target"
                repairs.append(
                    repair_migration_issue(
                        root,
                        cfg,
                        direction,
                        mutated,
                        journal,
                        file_backend,
                        issue_backend,
                        apply=True,
                    )
                )
                journal = load_journal(root)
            incomplete = journal_incomplete_keys(journal)
            if not incomplete:
                remove_gap_backlog_shim(root, apply=True)
                journal_path(root).unlink(missing_ok=True)
            else:
                write_transition_stamp(root, journal, apply=True)
                refresh_gap_backlog_shim(root, cfg, apply=True)
        finally:
            release_issue_store_lock(root)
    emit(
        {
            "verdict": "pass",
            "mode": "apply" if apply else "dry-run",
            "action": "store-rollback",
            "direction": direction,
            "issueCount": len(issues),
            "repairs": repairs,
            "rollbackInvariants": ROLLBACK_INVARIANTS,
        }
    )



def _parse_fm_list(value: str) -> list[str]:
    value = value.strip()
    if not value:
        return []
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [part.strip().strip("'\"") for part in inner.split(",") if part.strip()]
    return [value]


def _frontmatter_edges(fm: dict[str, str]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for key, rel in _EDGE_FM_KEYS.items():
        for target in _parse_fm_list(fm.get(key, "")):
            edges.append({"rel": rel, "target": target})
    return edges


def _edges_to_frontmatter_fields(edge_list: list[dict[str, Any]]) -> dict[str, str]:
    grouped: dict[str, list[str]] = {}
    for edge in edge_list:
        if not isinstance(edge, dict):
            continue
        rel = edge.get("rel")
        target = edge.get("target")
        if not isinstance(rel, str) or not isinstance(target, str):
            continue
        if rel not in _EDGE_FM_KEYS:
            continue
        grouped.setdefault(rel, []).append(target)
    out: dict[str, str] = {}
    for rel, targets in grouped.items():
        if len(targets) == 1:
            out[rel] = targets[0]
        else:
            out[rel] = "[" + ", ".join(targets) + "]"
    return out


def _norm_edge_list(edges: list[dict[str, Any]]) -> list[str]:
    return sorted(
        json.dumps(edge, sort_keys=True, ensure_ascii=False, default=str)
        for edge in edges
        if isinstance(edge, dict)
    )


def _gap_status_to_label(status: str | None) -> str | None:
    return gap_status_label(status)


def _gap_status_from_labels(labels: list[str]) -> str | None:
    return gap_status_from_labels(labels)


def _gap_schedule_from_labels(labels: list[str]) -> str | None:
    for label in labels:
        if label.startswith(_GAP_SCHEDULE_LABEL_PREFIX):
            return _decode_gap_schedule_from_label(label[len(_GAP_SCHEDULE_LABEL_PREFIX) :])
    return None


def _frozen_at_from_labels(labels: list[str]) -> str | None:
    for label in labels:
        if label.startswith(_FROZEN_AT_LABEL_PREFIX):
            return label[len(_FROZEN_AT_LABEL_PREFIX) :]
    return None


def _visibility_from_labels(labels: list[str]) -> str | None:
    for label in labels:
        if label.startswith(_VISIBILITY_LABEL_PREFIX):
            return label[len(_VISIBILITY_LABEL_PREFIX) :]
    return None


def _apply_visibility_label(labels: list[str], visibility: str | None) -> list[str]:
    out = [label for label in labels if not label.startswith(_VISIBILITY_LABEL_PREFIX)]
    if visibility:
        out.append(f"{_VISIBILITY_LABEL_PREFIX}{visibility}")
    return sorted(set(out))


def _apply_gap_labels(labels: list[str], lifecycle: ArtifactLifecycle, artifact_type: str) -> list[str]:
    out = [label for label in labels if label not in _GAP_STATUS_LABELS]
    if artifact_type == "gap":
        gap_label = _gap_status_to_label(lifecycle.gap_status)
        if gap_label:
            out.append(gap_label)
        if lifecycle.gap_schedule:
            out = [label for label in out if not label.startswith(_GAP_SCHEDULE_LABEL_PREFIX)]
            out.append(f"{_GAP_SCHEDULE_LABEL_PREFIX}{_encode_gap_schedule_for_label(lifecycle.gap_schedule)}")
    return sorted(set(out))


def _apply_frozen_labels(labels: list[str], lifecycle: ArtifactLifecycle) -> list[str]:
    out = list(labels)
    if lifecycle.frozen:
        out.append(FROZEN_LABEL)
        if lifecycle.frozen_at:
            out = [label for label in out if not label.startswith(_FROZEN_AT_LABEL_PREFIX)]
            out.append(f"{_FROZEN_AT_LABEL_PREFIX}{lifecycle.frozen_at}")
    return sorted(set(out))


def _file_body_content(raw: str) -> str:
    body = raw
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            body = raw[end + 4 :]
    return normalize_body(strip_markers_and_edges(body))


def _issue_state_from_frontmatter(fm: dict[str, str], artifact_type: str) -> str:
    status = fm.get("status", "").strip().lower()
    if artifact_type == "gap":
        return "closed" if status == "resolved" else "open"
    if status in {"complete", "resolved", "cancelled", "superseded"}:
        return "closed"
    return "open"


def _frontmatter_status_for_lifecycle(lifecycle: ArtifactLifecycle, artifact_type: str) -> str | None:
    """Map issue-store lifecycle to file ``status`` frontmatter (inverse of ``_issue_state_from_frontmatter``)."""
    if artifact_type == "gap":
        return lifecycle.gap_status or "open"
    if lifecycle.consumer_status:
        return lifecycle.consumer_status
    if lifecycle.issue_state == "closed":
        return "complete"
    if artifact_type in {"prd", "amendment", "tasks"}:
        return None
    return None


def extract_lifecycle_from_file(raw: str, artifact_type: str) -> ArtifactLifecycle:
    fm = parse_frontmatter_fields(raw)
    full_body = normalize_body(raw)
    edges_data = parse_edges_block(full_body)
    if edges_data:
        edge_list = list(edges_data.get("edges") or [])
        native_links = list(edges_data.get("native") or [])
    else:
        edge_list = _frontmatter_edges(fm)
        native_links = []

    frozen = fm.get("frozen", "").lower() in {"true", "yes", "1"}
    frozen_at = fm.get("frozen_at") or None
    visibility = fm.get("visibility") or parse_visibility_from_content(raw)

    gap_status: str | None = None
    gap_schedule: str | None = None
    if artifact_type == "gap":
        gap_status = fm.get("status") or None
        gap_schedule = fm.get("schedule") or None

    return ArtifactLifecycle(
        issue_state=_issue_state_from_frontmatter(fm, artifact_type),
        frozen=frozen,
        freeze_hash=None,
        frozen_at=frozen_at,
        edge_list=edge_list,
        native_links=native_links,
        gap_status=gap_status,
        gap_schedule=gap_schedule,
        visibility=visibility,
    )


def extract_lifecycle_from_record(record: Any) -> ArtifactLifecycle:
    full_body = reassemble_body(record.body, record.comments)
    edges_data = parse_edges_block(full_body) or {}
    edge_list = list(edges_data.get("edges") or [])
    native_links = list(record.native_links or edges_data.get("native") or [])

    frozen = FROZEN_LABEL in record.labels
    freeze_hash = parse_freeze_record_hash(record.comments)
    frozen_at = _frozen_at_from_labels(record.labels)

    artifact_type = record.artifact_type or "prd"
    gap_status = _gap_status_from_labels(record.labels) if artifact_type == "gap" else None
    gap_schedule = _gap_schedule_from_labels(record.labels) if artifact_type == "gap" else None

    content = strip_markers_and_edges(full_body)
    visibility = _visibility_from_labels(record.labels) or parse_visibility_from_content(content)

    consumer_status: str | None = None
    if artifact_type != "gap":
        consumer_status = status_from_labels(list(record.labels))
        if artifact_type == "brainstorm" and not consumer_status:
            consumer_status = "complete" if record.state == "closed" else None
        elif not consumer_status and record.state == "closed":
            consumer_status = "complete"

    return ArtifactLifecycle(
        issue_state=record.state,
        frozen=frozen,
        freeze_hash=freeze_hash,
        frozen_at=frozen_at,
        edge_list=edge_list,
        native_links=native_links,
        gap_status=gap_status,
        gap_schedule=gap_schedule,
        visibility=visibility,
        consumer_status=consumer_status,
    )


def render_file_with_lifecycle(
    content: str,
    lifecycle: ArtifactLifecycle,
    unit_id: str,
    artifact_type: str,
    *,
    title: str | None = None,
) -> str:
    fm_lines = ["---", f"id: {unit_id}"]
    if artifact_type != "prd":
        fm_lines.append(f"type: {artifact_type}")

    file_status = _frontmatter_status_for_lifecycle(lifecycle, artifact_type)
    if file_status is not None:
        fm_lines.append(f"status: {file_status}")

    if lifecycle.visibility:
        fm_lines.append(f"visibility: {lifecycle.visibility}")
    if title:
        fm_lines.append(f"title: {title}")
    if lifecycle.frozen:
        fm_lines.append("frozen: true")
    if lifecycle.frozen_at:
        fm_lines.append(f"frozen_at: {lifecycle.frozen_at}")
    if artifact_type == "gap" and lifecycle.gap_schedule:
        fm_lines.append(f"schedule: {lifecycle.gap_schedule}")

    for key, value in _edges_to_frontmatter_fields(lifecycle.edge_list).items():
        fm_lines.append(f"{key}: {value}")

    fm_lines.append("---")
    rendered = "\n".join(fm_lines) + "\n" + normalize_body(content)
    if lifecycle.edge_list or lifecycle.native_links:
        rendered += "\n\n" + build_edges_block(lifecycle.edge_list, lifecycle.native_links)
    return rendered


def lifecycle_equal(left: ArtifactLifecycle, right: ArtifactLifecycle) -> bool:
    return (
        left.issue_state == right.issue_state
        and left.frozen == right.frozen
        and left.freeze_hash == right.freeze_hash
        and left.frozen_at == right.frozen_at
        and _norm_edge_list(left.edge_list) == _norm_edge_list(right.edge_list)
        and _norm_edge_list(left.native_links) == _norm_edge_list(right.native_links)
        and left.gap_status == right.gap_status
        and left.gap_schedule == right.gap_schedule
        and left.visibility == right.visibility
    )




_INDEX_STATUS_CACHE: dict[str, str] | None = None


_COMPLETION_LOG_STATUS_CACHE: dict[str, str] | None = None


def _completion_log_status_map(root: Path) -> dict[str, str]:
    global _COMPLETION_LOG_STATUS_CACHE
    if _COMPLETION_LOG_STATUS_CACHE is not None:
        return _COMPLETION_LOG_STATUS_CACHE
    mapping: dict[str, str] = {}
    log_path = root / "docs" / "prds" / "COMPLETION-LOG.md"
    if log_path.is_file():
        notes_by_prd: dict[str, list[str]] = {}
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|") or "---" in line:
                continue
            cols = [c.strip() for c in line.strip("|").split("|")]
            if len(cols) < 4 or not re.match(r"^\d{3}$", cols[1]):
                continue
            notes_by_prd.setdefault(cols[1], []).append(cols[3].lower())
        complete_markers = (
            "deliver complete",
            "shipped via",
            "deliver-terminal",
            "deliver merged",
            "squash-merged",
            "squash merged",
        )
        for num, notes in notes_by_prd.items():
            blob = " ".join(notes)
            if any(marker in blob for marker in complete_markers):
                mapping[num] = "complete"
    _COMPLETION_LOG_STATUS_CACHE = mapping
    return mapping


def _legacy_index_status_map(root: Path) -> dict[str, str]:
    global _INDEX_STATUS_CACHE
    if _INDEX_STATUS_CACHE is not None:
        return _INDEX_STATUS_CACHE
    mapping: dict[str, str] = {}
    index_path = root / "docs" / "prds" / "INDEX.md"
    if index_path.is_file():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|") or "---" in line:
                continue
            cols = [c.strip() for c in line.strip("|").split("|")]
            if len(cols) < 5 or not re.match(r"^\d{3}$", cols[0]):
                continue
            num, status = cols[0], cols[4].lower()
            if "complete" in status:
                mapping[num] = "complete"
            elif "superseded" in status:
                mapping[num] = "superseded"
            elif "not-started" in status:
                mapping[num] = "not-started"
    _INDEX_STATUS_CACHE = mapping
    return mapping


def _prd_number_for_status(unit_id: str, artifact_type: str, body_path: str | None = None) -> str | None:
    m = re.match(r"^(\d{3})-", unit_id)
    if m:
        return m.group(1)
    norm = (body_path or "").replace("\\", "/")
    if artifact_type == "amendment":
        path_match = re.search(r"/(\d{3})-[^/]+/amendments/", norm)
        if path_match:
            return path_match.group(1)
    if artifact_type == "tasks":
        path_match = re.search(r"/(\d{3})-[^/]+/tasks-", norm)
        if path_match:
            return path_match.group(1)
    return None


def _consumer_status_for_prd_number(root: Path, num: str) -> str | None:
    index_status = _legacy_index_status_map(root).get(num)
    if index_status == "superseded":
        return "superseded"
    log_status = _completion_log_status_map(root).get(num)
    if log_status:
        return log_status
    return index_status


def _consumer_status_for_artifact(
    root: Path,
    unit_id: str,
    artifact_type: str,
    *,
    body_path: str | None = None,
) -> str | None:
    if artifact_type == "brainstorm":
        # Brainstorms are requirements capture — not deliverable work (R52/R53).
        return "complete"
    if artifact_type not in {"prd", "tasks", "amendment"}:
        return None
    num = _prd_number_for_status(unit_id, artifact_type, body_path)
    if not num:
        return None
    return _consumer_status_for_prd_number(root, num)


def _workflow_state_for_consumer_status(consumer_status: str | None) -> str | None:
    if consumer_status in {"complete", "superseded", "cancelled", "resolved"}:
        return "closed"
    if consumer_status == "not-started":
        return "open"
    return None


def _apply_status_labels(labels: list[str], consumer_status: str | None) -> list[str]:
    out = [label for label in labels if not label.startswith(_STATUS_LABEL_PREFIX)]
    if consumer_status:
        out.append(status_label(consumer_status))
    return sorted(set(out))


def infer_unit_id(rel_path: str, content: str) -> str:
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            fm = parse_frontmatter_fields(content[: end + 4])
            unit = fm.get("id", "").strip()
            if unit:
                return unit
    norm = rel_path.replace("\\", "/")
    if "/planning/brainstorm/" in norm:
        return Path(norm).parent.name
    if norm.startswith("docs/brainstorms/"):
        return f"brainstorm-{slugify(Path(norm).stem)[:48]}"
    if "/planning/decision/" in norm:
        return Path(norm).parent.name
    if norm.startswith("docs/decisions/") and not norm.endswith("INDEX.md"):
        return f"decision-{slugify(Path(norm).stem)[:48]}"
    stem = Path(rel_path).stem
    if stem.startswith("tasks-"):
        return stem[len("tasks-") :]
    return stem.replace("_", "-")


def rel_path(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def should_skip_file(rel: str) -> bool:
    base = Path(rel).name
    if base in SKIP_BASENAMES:
        return True
    if rel.startswith("docs/prds/_fixture-materialize/"):
        return True
    if rel.endswith("docs/decisions/INDEX.md") or rel.endswith("docs/decisions/SUPERSEDED.log"):
        return True
    return False


def discover_file_artifacts(root: Path) -> list[MigrationArtifact]:
    artifacts: list[MigrationArtifact] = []
    for walk_root in WALK_ROOTS:
        base = root / walk_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            if not path.is_file():
                continue
            rel = rel_path(root, path)
            if should_skip_file(rel):
                continue
            raw = path.read_text(encoding="utf-8")
            artifact_type = infer_artifact_type(rel)
            lifecycle = extract_lifecycle_from_file(raw, artifact_type)
            content = _file_body_content(raw)
            fm = parse_frontmatter_fields(raw)
            artifacts.append(
                MigrationArtifact(
                    source_path=rel,
                    body_path=rel,
                    unit_id=infer_unit_id(rel, raw),
                    content=content,
                    digest=content_hash(content),
                    artifact_type=artifact_type,
                    lifecycle=lifecycle,
                    title=fm.get("title") or None,
                )
            )
    return artifacts


def issue_source_path(record_id: str) -> str:
    return f"issue:{record_id}"


def extract_issue_content(record: Any) -> str:
    full_body = reassemble_body(record.body, record.comments)
    return normalize_body(strip_markers_and_edges(full_body))


def body_path_from_journal(root: Path, unit_id: str) -> str | None:
    journal = load_journal(root)
    for entry in journal.get("entries", {}).values():
        if not isinstance(entry, dict):
            continue
        if entry.get("unitId") == unit_id and entry.get("bodyPath"):
            return str(entry["bodyPath"])
    return None


def title_from_journal(root: Path, unit_id: str) -> str | None:
    journal = load_journal(root)
    for entry in journal.get("entries", {}).values():
        if not isinstance(entry, dict):
            continue
        if entry.get("unitId") == unit_id and entry.get("title"):
            return str(entry["title"])
    return None


def default_body_path(unit_id: str, artifact_type: str) -> str:
    if artifact_type == "brainstorm":
        if unit_id.startswith("brainstorm-"):
            return f"docs/planning/brainstorm/{unit_id}/{unit_id}.md"
        return f"docs/brainstorms/{unit_id}.md"
    if artifact_type == "decision":
        if unit_id.startswith("decision-"):
            return f"docs/planning/decision/{unit_id}/{unit_id}.md"
        return f"docs/decisions/{unit_id}.md"
    if artifact_type == "gap":
        return f"docs/planning/gap/{unit_id}.md"
    if artifact_type == "tasks":
        return f"docs/prds/tasks-{unit_id}.md"
    return f"docs/prds/{unit_id}/{unit_id}.md"


def discover_issue_artifacts(root: Path, cfg: dict[str, Any]) -> list[MigrationArtifact]:
    key_result = validate_project_key(root, cfg)
    if key_result.get("verdict") != "ok":
        fail(key_result.get("message") or key_result.get("error", "invalid-project-key"))
    project_key = str(key_result["projectKey"])
    store = cfg.get("planning", {}).get("store", {})
    provider = str(store.get("issuesProvider", "none"))
    client = IssuesClient(root, provider)
    records = client.issue_search(project_key=project_key)
    artifacts: list[MigrationArtifact] = []
    for record in records:
        lifecycle = extract_lifecycle_from_record(record)
        content = extract_issue_content(record)
        artifact_type = record.artifact_type or "prd"
        body_path = body_path_from_journal(root, record.unit_id) or default_body_path(
            record.unit_id, artifact_type
        )
        src = issue_source_path(record.id)
        artifacts.append(
            MigrationArtifact(
                source_path=src,
                body_path=body_path,
                unit_id=record.unit_id,
                content=content,
                digest=content_hash(content),
                artifact_type=record.artifact_type or infer_artifact_type(body_path),
                lifecycle=lifecycle,
                issue_id=record.id,
                title=title_from_journal(root, record.unit_id),
            )
        )
    return artifacts


_MIGRATION_LINK_RELS = frozenset({"depends", "sub-issue-of", "blocks"})


def _migration_create_order(artifacts: list[MigrationArtifact]) -> list[MigrationArtifact]:
    """Order file artifacts so link targets exist before sources (PRD 056 R4)."""
    by_id = {artifact.unit_id: artifact for artifact in artifacts}
    prereqs: dict[str, set[str]] = {artifact.unit_id: set() for artifact in artifacts}
    for artifact in artifacts:
        for edge in artifact.lifecycle.edge_list:
            if not isinstance(edge, dict):
                continue
            rel = str(edge.get("rel", ""))
            target = str(edge.get("target", ""))
            if rel in _MIGRATION_LINK_RELS and target in by_id:
                prereqs[artifact.unit_id].add(target)
    ordered: list[MigrationArtifact] = []
    seen: set[str] = set()

    def visit(unit_id: str) -> None:
        if unit_id in seen or unit_id not in by_id:
            return
        for dep in prereqs.get(unit_id, ()):
            visit(dep)
        if unit_id not in seen:
            seen.add(unit_id)
            ordered.append(by_id[unit_id])

    for artifact in artifacts:
        visit(artifact.unit_id)
    return ordered


def discover_artifacts(root: Path, direction: str, cfg: dict[str, Any]) -> list[MigrationArtifact]:
    if direction == DIRECTION_FILES_TO_ISSUES:
        return discover_file_artifacts(root)
    if direction == DIRECTION_ISSUES_TO_FILES:
        return discover_issue_artifacts(root, cfg)
    fail("invalid-direction", direction=direction)


def _maybe_inject_fail(after_state: str) -> None:
    target = os.environ.get("SW_MIGRATE_INJECT_FAIL_AFTER", "").strip()
    if target and target == after_state:
        fail("injected-failure", code="inject-fail", after=after_state)


def _journal_entry(journal: dict[str, Any], artifact: MigrationArtifact) -> dict[str, Any]:
    key = idempotency_key(artifact.source_path, artifact.digest)
    entries = journal["entries"]
    raw = entries.get(key)
    if isinstance(raw, dict):
        return raw
    return {
        "state": "pending",
        "idempotencyKey": key,
        "sourcePath": artifact.source_path,
        "bodyPath": artifact.body_path,
        "unitId": artifact.unit_id,
        "contentHash": artifact.digest,
    }


def _set_entry(journal: dict[str, Any], artifact: MigrationArtifact, entry: dict[str, Any]) -> None:
    key = idempotency_key(artifact.source_path, artifact.digest)
    journal["entries"][key] = entry


def _visibility_gate_content(artifact: MigrationArtifact) -> str:
    if artifact.lifecycle.visibility:
        return f"---\nvisibility: {artifact.lifecycle.visibility}\n---\n{artifact.content}"
    return artifact.content


def _visibility_ok(root: Path, cfg: dict[str, Any], artifact: MigrationArtifact) -> bool:
    from planning_store import issue_store_visibility_allowed

    return issue_store_visibility_allowed(
        root, cfg, artifact.unit_id, artifact.body_path, _visibility_gate_content(artifact)
    )


def _guard_create_secrets(artifact: MigrationArtifact, *, path_hint: str) -> None:
    secret_scan_text(artifact.content, path_hint=path_hint)


def _record_to_snapshot(record: Any) -> IssueSnapshot:
    return IssueSnapshot(
        title=record.title,
        body=record.body,
        state=record.state,
        labels=list(record.labels),
        comments=list(record.comments),
        native_links=list(record.native_links),
        etag=record.etag,
        updated_at=record.updated_at,
    )


def _lookup_issue_record(
    root: Path,
    project_key: str,
    unit_id: str,
    body_path: str,
    client: IssuesClient,
) -> Any:
    index = load_issue_unit_index(root)
    idx_key = issue_index_key(project_key, unit_id)
    issue_id = index.get(idx_key)
    if issue_id:
        try:
            record = client.issue_get(issue_id)
        except IssueNotFound:
            record = None
        else:
            return record
    matches = client.issue_search(
        project_key=project_key,
        unit_id=unit_id,
        artifact_type=infer_artifact_type(body_path),
    )
    if not matches:
        raise IssueNotFound(f"no issue for unit {unit_id}")
    record = matches[0]
    index[idx_key] = record.id
    save_issue_unit_index(root, index)
    return record


def _create_issue_with_lifecycle(
    root: Path,
    cfg: dict[str, Any],
    artifact: MigrationArtifact,
    issue_backend: IssueStoreBackend,
    *,
    apply: bool,
) -> str:
    if not apply:
        return "dry-run-issue"

    project_key = issue_backend.project_key
    provider = str(cfg.get("planning", {}).get("store", {}).get("issuesProvider", "none"))
    client = IssuesClient(root, provider)

    consumer_status = _consumer_status_for_artifact(root, artifact.unit_id, artifact.artifact_type, body_path=artifact.body_path)
    labels = _apply_status_labels(
        _apply_visibility_label(
            _apply_frozen_labels(
                _apply_gap_labels(
                    sorted({project_label(project_key), type_label(artifact.artifact_type)}),
                    artifact.lifecycle,
                    artifact.artifact_type,
                ),
                artifact.lifecycle,
            ),
            artifact.lifecycle.visibility,
        ),
        consumer_status,
    )
    title = f"{title_prefix(project_key)} {artifact.artifact_type}:{artifact.unit_id}"
    native_links = project_native_links_from_edges(
        root,
        artifact.lifecycle.edge_list,
        artifact.lifecycle.native_links,
        project_key,
    )
    body = compose_issue_body(
        project_key,
        artifact.artifact_type,
        artifact.unit_id,
        artifact.content,
        edges=artifact.lifecycle.edge_list or None,
        native_links=native_links or None,
    )
    if provider == "jira":
        body, extra_comments = chunk_body_for_jira_cloud(body, [])
    else:
        body, extra_comments = chunk_body_if_needed(body, [])

    try:
        record = _lookup_issue_record(root, project_key, artifact.unit_id, artifact.body_path, client)
    except IssueNotFound:
        record = client.issue_create(
            title=title,
            body=body,
            labels=labels,
            project_key=project_key,
            artifact_type=artifact.artifact_type,
            unit_id=artifact.unit_id,
            native_links=native_links or None,
        )
    else:
        try:
            workflow_state = _workflow_state_for_consumer_status(consumer_status) or artifact.lifecycle.issue_state
            record = client.issue_update(
                record.id,
                title=title,
                body=body,
                labels=labels,
                state=workflow_state,
                native_links=native_links or None,
                if_match=record.etag,
                allow_locked=True,
            )
        except IssueRevisionConflict as exc:
            fail(
                "revision-conflict",
                code="revision-conflict",
                expected=exc.expected,
                actual=exc.actual,
            )

    chunk_comment_ids: list[str] = []
    for comment in extra_comments:
        secret_scan_text(comment.body, path_hint=artifact.body_path)
        posted = client.issue_comment(record.id, comment.body, markers=comment.markers)
        chunk_comment_ids.append(posted.id)
        record = client.issue_get(record.id)
    if chunk_comment_ids:
        manifest_body = rewrite_chunk_manifest(body, chunk_comment_ids)
        if manifest_body != record.body:
            record = client.issue_update(
                record.id,
                body=manifest_body,
                if_match=record.etag,
                allow_locked=True,
            )

    if artifact.lifecycle.frozen:
        record = client.issue_lock(record.id, if_match=record.etag)
        record = client.issue_label(record.id, labels, if_match=record.etag)
        snapshot = _record_to_snapshot(record)
        digest = artifact.lifecycle.freeze_hash or canonical_hash(snapshot)
        if not parse_freeze_record_hash(record.comments):
            freeze_body = build_freeze_record_body(digest)
            secret_scan_text(freeze_body, path_hint="sw-freeze-record")
            client.issue_comment(record.id, freeze_body, markers=["sw-freeze-record"])
            record = client.issue_get(record.id)
    elif artifact.lifecycle.issue_state == "closed":
        record = client.issue_update(record.id, state="closed", if_match=record.etag)

    index = load_issue_unit_index(root)
    index[issue_index_key(project_key, artifact.unit_id)] = record.id
    save_issue_unit_index(root, index)
    return record.id


def _create_file_with_lifecycle(
    artifact: MigrationArtifact,
    file_backend: InRepoPublicBackend,
    *,
    apply: bool,
) -> str:
    rendered = render_file_with_lifecycle(
        artifact.content,
        artifact.lifecycle,
        artifact.unit_id,
        artifact.artifact_type,
        title=artifact.title,
    )
    if apply:
        result = file_backend.put(artifact.unit_id, artifact.body_path, rendered)
        if result.verdict != "ok":
            fail("file-create-failed", unitId=artifact.unit_id, bodyPath=artifact.body_path)
    return artifact.body_path


def _create_target(
    root: Path,
    cfg: dict[str, Any],
    direction: str,
    artifact: MigrationArtifact,
    file_backend: InRepoPublicBackend,
    issue_backend: IssueStoreBackend,
    *,
    apply: bool,
) -> str | None:
    if direction == DIRECTION_FILES_TO_ISSUES:
        if not _visibility_ok(root, cfg, artifact):
            return None
        if apply:
            _guard_create_secrets(artifact, path_hint=artifact.body_path)
        return _create_issue_with_lifecycle(
            root, cfg, artifact, issue_backend, apply=apply
        )
    if apply:
        _guard_create_secrets(artifact, path_hint=artifact.body_path)
    return _create_file_with_lifecycle(artifact, file_backend, apply=apply)




def _expected_issue_verify_content(content: str, provider: str) -> str:
  """Provider-aware body form for files-to-issues verify (GitHub stores markdown as-is)."""
  if provider == "jira":
    return jira_markdown_canonical(content)
  return normalize_body(content)


def _expected_verify_lifecycle(
    root: Path,
    artifact: MigrationArtifact,
    cfg: dict[str, Any],
    project_key: str,
    *,
    freeze_hash: str | None,
) -> ArtifactLifecycle:
    consumer_status = _consumer_status_for_artifact(
        root,
        artifact.unit_id,
        artifact.artifact_type,
        body_path=artifact.body_path,
    )
    issue_state = _workflow_state_for_consumer_status(consumer_status) or artifact.lifecycle.issue_state
    native_links = project_native_links_from_edges(
        root,
        artifact.lifecycle.edge_list,
        artifact.lifecycle.native_links,
        project_key,
    )
    return ArtifactLifecycle(
        issue_state=issue_state,
        frozen=artifact.lifecycle.frozen,
        freeze_hash=freeze_hash,
        frozen_at=artifact.lifecycle.frozen_at,
        edge_list=artifact.lifecycle.edge_list,
        native_links=native_links,
        gap_status=artifact.lifecycle.gap_status,
        gap_schedule=artifact.lifecycle.gap_schedule,
        visibility=artifact.lifecycle.visibility,
        consumer_status=consumer_status,
    )

def _verify_target(
    root: Path,
    direction: str,
    artifact: MigrationArtifact,
    file_backend: InRepoPublicBackend,
    issue_backend: IssueStoreBackend,
    cfg: dict[str, Any],
    *,
    apply: bool,
) -> bool:
    if not apply:
        return True
    if direction == DIRECTION_FILES_TO_ISSUES:
        provider = str(cfg.get("planning", {}).get("store", {}).get("issuesProvider", "none"))
        client = IssuesClient(root, provider)
        try:
            record = _lookup_issue_record(
                root,
                issue_backend.project_key,
                artifact.unit_id,
                artifact.body_path,
                client,
            )
        except IssueNotFound:
            return False
        got_content = extract_issue_content(record)
        got_lifecycle = extract_lifecycle_from_record(record)
        expected_content = _expected_issue_verify_content(artifact.content, provider)
        if content_hash(got_content) != content_hash(expected_content):
            return False
        if artifact.lifecycle.frozen and not got_lifecycle.frozen:
            return False
        if artifact.lifecycle.freeze_hash and got_lifecycle.freeze_hash != artifact.lifecycle.freeze_hash:
            return False
        return lifecycle_equal(
            _expected_verify_lifecycle(
                root,
                artifact,
                cfg,
                issue_backend.project_key,
                freeze_hash=got_lifecycle.freeze_hash,
            ),
            got_lifecycle,
        )

    path = root / artifact.body_path
    if not path.is_file():
        return False
    raw = path.read_text(encoding="utf-8")
    got_content = _file_body_content(raw)
    got_lifecycle = extract_lifecycle_from_file(raw, artifact.artifact_type)
    if content_hash(got_content) != artifact.digest:
        return False
    expected = ArtifactLifecycle(
        issue_state=artifact.lifecycle.issue_state,
        frozen=artifact.lifecycle.frozen,
        freeze_hash=None,
        frozen_at=artifact.lifecycle.frozen_at,
        edge_list=artifact.lifecycle.edge_list,
        native_links=artifact.lifecycle.native_links,
        gap_status=artifact.lifecycle.gap_status,
        gap_schedule=artifact.lifecycle.gap_schedule,
        visibility=artifact.lifecycle.visibility,
    )
    return lifecycle_equal(expected, got_lifecycle)


def _remove_source(
    root: Path,
    direction: str,
    artifact: MigrationArtifact,
    *,
    apply: bool,
) -> None:
    if not apply:
        return
    if direction == DIRECTION_FILES_TO_ISSUES:
        src = root / artifact.source_path
        if src.is_file():
            src.unlink()
        return
    if artifact.issue_id:
        store = cfg_issues_client(root)
        store.mark_tombstone(artifact.issue_id)


def cfg_issues_client(root: Path) -> IssuesClient:
    cfg = load_workflow_config(root)
    provider = str(cfg.get("planning", {}).get("store", {}).get("issuesProvider", "none"))
    return IssuesClient(root, provider)


def process_artifact(
    root: Path,
    cfg: dict[str, Any],
    direction: str,
    artifact: MigrationArtifact,
    journal: dict[str, Any],
    file_backend: InRepoPublicBackend,
    issue_backend: IssueStoreBackend,
    *,
    apply: bool,
    plan: list[dict[str, Any]],
) -> None:
    entry = _journal_entry(journal, artifact)
    state = str(entry.get("state", "pending"))
    if state == "source-removed":
        plan.append({"unitId": artifact.unit_id, "sourcePath": artifact.source_path, "action": "skip", "state": state})
        return

    while state != "source-removed":
        if state == "pending":
            plan.append({"unitId": artifact.unit_id, "sourcePath": artifact.source_path, "action": "create"})
            target_ref = _create_target(
                root, cfg, direction, artifact, file_backend, issue_backend, apply=apply
            )
            if target_ref is None:
                plan.append(
                    {
                        "unitId": artifact.unit_id,
                        "sourcePath": artifact.source_path,
                        "action": "refused",
                        "reason": "visibility",
                    }
                )
                return
            entry["state"] = "created"
            entry["targetRef"] = target_ref
            if artifact.title:
                entry["title"] = artifact.title
            _set_entry(journal, artifact, entry)
            save_journal(root, journal, apply=apply)
            _maybe_inject_fail("created")
            state = "created"
            continue

        if state == "created":
            plan.append({"unitId": artifact.unit_id, "sourcePath": artifact.source_path, "action": "verify"})
            if apply:
                _create_target(
                    root, cfg, direction, artifact, file_backend, issue_backend, apply=True
                )
            if not _verify_target(
                root, direction, artifact, file_backend, issue_backend, cfg, apply=apply
            ):
                fail("verify-failed", unitId=artifact.unit_id, sourcePath=artifact.source_path)
            entry["state"] = "verified"
            _set_entry(journal, artifact, entry)
            save_journal(root, journal, apply=apply)
            _maybe_inject_fail("verified")
            state = "verified"
            continue

        if state == "verified":
            plan.append({"unitId": artifact.unit_id, "sourcePath": artifact.source_path, "action": "remove-source"})
            _remove_source(root, direction, artifact, apply=apply)
            entry["state"] = "source-removed"
            _set_entry(journal, artifact, entry)
            save_journal(root, journal, apply=apply)
            _maybe_inject_fail("source-removed")
            state = "source-removed"
            continue

        fail("invalid-journal-state", state=state, unitId=artifact.unit_id)


def run_store_migration(root: Path, direction: str, *, apply: bool = False) -> None:
    root = root.resolve()
    if direction not in DIRECTIONS:
        fail("invalid-direction", direction=direction)
    assert_quiesced(root)
    cfg = load_workflow_config(root)
    journal = load_journal(root)
    if journal.get("direction") and journal["direction"] != direction:
        entries = journal.get("entries", {})
        incomplete = [
            key
            for key, entry in entries.items()
            if isinstance(entry, dict) and entry.get("state") != "source-removed"
        ]
        if incomplete:
            fail(
                "journal-direction-mismatch",
                journalDirection=journal["direction"],
                requested=direction,
                incomplete=incomplete,
            )
    journal["direction"] = direction

    file_backend = InRepoPublicBackend(root, cfg)
    issue_backend = IssueStoreBackend(root, cfg)

    lock_held = False
    if apply:
        acquire_issue_store_lock(root)
        lock_held = True
    artifacts: list[MigrationArtifact] = []
    plan: list[dict[str, Any]] = []
    try:
        artifacts = discover_artifacts(root, direction, cfg)
        if direction == DIRECTION_FILES_TO_ISSUES:
            artifacts = _migration_create_order(artifacts)
        for artifact in artifacts:
            process_artifact(
                root,
                cfg,
                direction,
                artifact,
                journal,
                file_backend,
                issue_backend,
                apply=apply,
                plan=plan,
            )
            journal = load_journal(root)
    finally:
        if apply:
            journal = load_journal(root)
            write_transition_stamp(root, journal, apply=True)
            refresh_gap_backlog_shim(root, cfg, apply=True)
            if not journal_incomplete_keys(journal):
                remove_gap_backlog_shim(root, apply=True)
        if lock_held:
            release_issue_store_lock(root)

    refused_count = sum(1 for item in plan if item.get("action") == "refused")

    emit(
        {
            "verdict": "pass",
            "mode": "apply" if apply else "dry-run",
            "direction": direction,
            "artifactCount": len(artifacts),
            "refusedCount": refused_count,
            "plan": plan,
            "journalPath": JOURNAL_REL,
            "rollbackInvariants": ROLLBACK_INVARIANTS,
        }
    )



def run_backfill_labels(root: Path, *, apply: bool = False) -> None:
    """Refresh type/status/gap labels on existing Jira issues from legacy INDEX + paths."""
    root = root.resolve()
    cfg = load_workflow_config(root)
    issue_backend = IssueStoreBackend(root, cfg)
    provider = str(cfg.get("planning", {}).get("store", {}).get("issuesProvider", "none"))
    client = IssuesClient(root, provider)
    journal = load_journal(root)
    unit_to_path: dict[str, str] = {}
    for entry in journal.get("entries", {}).values():
        if isinstance(entry, dict) and entry.get("unitId") and entry.get("bodyPath"):
            unit_to_path[str(entry["unitId"])] = str(entry["bodyPath"])
    records = client.issue_search(project_key=issue_backend.project_key)
    updated = 0
    for record in records:
        body_path = unit_to_path.get(record.unit_id or "", "")
        artifact_type = record.artifact_type or infer_artifact_type(body_path or record.unit_id)
        if body_path:
            artifact_type = infer_artifact_type(body_path)
        consumer_status = _consumer_status_for_artifact(root, record.unit_id or "", artifact_type, body_path=body_path or None)
        labels = sorted(set(record.labels))
        labels = [l for l in labels if not l.startswith("sw:prd") and not l.startswith("sw:amendment") and not l.startswith("sw:brainstorm") and not l.startswith("sw:decision")]
        labels.append(type_label(artifact_type))
        if artifact_type == "gap":
            gap_stat = _gap_status_from_labels(record.labels) or "open"
            labels = _apply_gap_labels(labels, ArtifactLifecycle(
                issue_state=record.state, frozen=False, freeze_hash=None, frozen_at=None,
                gap_status=gap_stat,
            ), "gap")
        labels = _apply_status_labels(labels, consumer_status)
        workflow_state = _workflow_state_for_consumer_status(consumer_status)
        labels_changed = sorted(set(labels)) != sorted(set(record.labels))
        state_changed = workflow_state is not None and workflow_state != record.state
        if not labels_changed and not state_changed:
            continue
        update_kwargs: dict[str, Any] = {
            "labels": labels,
            "if_match": record.etag,
            "allow_locked": True,
        }
        if state_changed:
            update_kwargs["state"] = workflow_state
        if apply:
            client.issue_update(record.id, **update_kwargs)
        updated += 1
    emit({
        "verdict": "pass",
        "action": "backfill-labels",
        "mode": "apply" if apply else "dry-run",
        "issueCount": len(records),
        "updatedCount": updated,
    })


def _normalize_edge_target(target: str, path_to_unit: dict[str, str]) -> str:
    t = target.strip()
    if not t:
        return t
    if "/" not in t and not t.endswith(".md"):
        return t
    norm = t.replace("\\", "/")
    if norm in path_to_unit:
        return path_to_unit[norm]
    return infer_unit_id(norm, "")


def _build_path_to_unit_map(root: Path, journal: dict[str, Any], records: list[Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for entry in journal.get("entries", {}).values():
        if not isinstance(entry, dict):
            continue
        uid = entry.get("unitId")
        body_path = entry.get("bodyPath")
        if isinstance(uid, str) and isinstance(body_path, str):
            mapping[body_path.replace("\\", "/")] = uid
    for record in records:
        uid = str(record.unit_id or "").strip()
        if not uid:
            continue
        body_path = body_path_from_journal(root, uid) or default_body_path(
            uid, record.artifact_type or infer_artifact_type(uid)
        )
        mapping[body_path.replace("\\", "/")] = uid
    return mapping


def _normalize_edge_list(edge_list: list[dict[str, Any]], path_to_unit: dict[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for edge in edge_list:
        if not isinstance(edge, dict):
            continue
        rel = edge.get("rel")
        target = edge.get("target")
        if not isinstance(rel, str) or not isinstance(target, str):
            continue
        normalized_target = _normalize_edge_target(target, path_to_unit)
        key = json.dumps({"rel": rel, "target": normalized_target}, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append({"rel": rel, "target": normalized_target})
    return out


def _reciprocal_edges(unit_id: str, artifact_type: str, edge_list: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    implied: list[tuple[str, dict[str, Any]]] = []
    for edge in edge_list:
        rel = str(edge.get("rel", ""))
        target = str(edge.get("target", ""))
        if not rel or not target:
            continue
        inverse = _EDGE_INVERSE_REL.get(rel)
        if inverse:
            implied.append((target, {"rel": inverse, "target": unit_id}))
        if rel == "prd" and artifact_type == "brainstorm":
            implied.append((target, {"rel": "brainstorm", "target": unit_id}))
        if rel == "amends" and artifact_type == "amendment":
            implied.append((target, {"rel": "extends", "target": unit_id}))
    return implied


def run_backfill_edges(root: Path, *, apply: bool = False) -> None:
    """Normalize sw-edges targets to unit ids and add reciprocals across the issue store."""
    root = root.resolve()
    cfg = load_workflow_config(root)
    issue_backend = IssueStoreBackend(root, cfg)
    provider = str(cfg.get("planning", {}).get("store", {}).get("issuesProvider", "none"))
    client = IssuesClient(root, provider)
    journal = load_journal(root)
    records = client.issue_search(project_key=issue_backend.project_key)
    path_to_unit = _build_path_to_unit_map(root, journal, records)
    unit_edges: dict[str, list[dict[str, Any]]] = {}
    unit_types: dict[str, str] = {}
    unit_records: dict[str, Any] = {}
    for record in records:
        uid = str(record.unit_id or "").strip()
        if not uid:
            continue
        artifact_type = record.artifact_type or infer_artifact_type(uid)
        unit_types[uid] = artifact_type
        unit_records[uid] = record
        lifecycle = extract_lifecycle_from_record(record)
        unit_edges[uid] = _normalize_edge_list(lifecycle.edge_list, path_to_unit)

    for uid, edges in list(unit_edges.items()):
        for target_uid, reciprocal in _reciprocal_edges(uid, unit_types.get(uid, "prd"), edges):
            if target_uid not in unit_edges:
                continue
            existing = {(e["rel"], e["target"]) for e in unit_edges[target_uid]}
            pair = (reciprocal["rel"], reciprocal["target"])
            if pair not in existing:
                unit_edges[target_uid].append(reciprocal)

    updated = 0
    for uid, edges in unit_edges.items():
        record = unit_records.get(uid)
        if record is None:
            continue
        lifecycle = extract_lifecycle_from_record(record)
        if _norm_edge_list(edges) == _norm_edge_list(lifecycle.edge_list):
            continue
        content = strip_markers_and_edges(reassemble_body(record.body, record.comments))
        body_path = body_path_from_journal(root, uid) or default_body_path(uid, unit_types.get(uid, "prd"))
        artifact_type = unit_types.get(uid, infer_artifact_type(body_path))
        new_body = compose_issue_body(
            issue_backend.project_key,
            artifact_type,
            uid,
            content,
            edges=edges,
            native_links=lifecycle.native_links or None,
        )
        if apply:
            client.issue_update(record.id, body=new_body, if_match=record.etag, allow_locked=True)
        updated += 1

    emit({
        "verdict": "pass",
        "action": "backfill-edges",
        "mode": "apply" if apply else "dry-run",
        "issueCount": len(records),
        "updatedCount": updated,
    })


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Issue-store migration engine")
    parser.add_argument("repo_root")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["migrate", "doctor", "rollback", "scan-quiesce", "backfill-labels"],
        default="migrate",
    )
    parser.add_argument("direction", nargs="?", choices=sorted(DIRECTIONS))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = Path(args.repo_root)
    if args.command == "doctor":
        run_store_doctor(root, apply=args.apply)
    elif args.command == "rollback":
        rollback_store_migration(root, apply=args.apply)
    elif args.command == "scan-quiesce":
        emit({"verdict": "pass", "blockers": scan_quiesce_blockers(root)})
    elif args.command == "backfill-labels":
        run_backfill_labels(root, apply=args.apply)
    else:
        if not args.direction:
            fail("direction required for migrate")
        run_store_migration(root, args.direction, apply=args.apply)
