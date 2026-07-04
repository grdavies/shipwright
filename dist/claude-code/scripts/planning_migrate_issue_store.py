#!/usr/bin/env python3
"""PRD 044 Phase 1+2 — issue-store migration engine (dry-run default, journaled, lifecycle-aware)."""

from __future__ import annotations

import json
import os
import re
import sys
import time
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
}
_GAP_STATUS_LABELS = frozenset({"open", "gap-scheduled", "resolved"})
_GAP_SCHEDULE_LABEL_PREFIX = "sw:gap-schedule:"
_FROZEN_AT_LABEL_PREFIX = "sw:frozen-at:"
_VISIBILITY_LABEL_PREFIX = "sw:visibility:"


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
from planning_canonical import (  # noqa: E402
    FROZEN_LABEL,
    IssueSnapshot,
    build_edges_block,
    build_freeze_record_body,
    canonical_hash,
    chunk_body_if_needed,
    compose_issue_body,
    infer_artifact_type,
    normalize_body,
    parse_edges_block,
    parse_freeze_record_hash,
    project_label,
    reassemble_body,
    strip_markers_and_edges,
    title_prefix,
    type_label,
)
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
        "COMPLETION-LOG.md",
        "GAP-BACKLOG.md",
        "FEEDBACK-CHECKLIST.md",
    }
)
WALK_ROOTS = ("docs/planning", "docs/prds")


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


def gap_backlog_is_readonly(root: Path) -> bool:
    if migration_in_transition(root):
        return True
    dirs = pp_load_planning_dirs(root)
    gap_path = root / dirs.prds / "GAP-BACKLOG.md"
    if not gap_path.is_file():
        return False
    return GAP_BACKLOG_SHIM_MARKER in gap_path.read_text(encoding="utf-8")


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
    if not status:
        return None
    lowered = status.lower()
    if lowered in {"planned", "scheduled"}:
        return "gap-scheduled"
    if lowered == "resolved":
        return "resolved"
    return "open"


def _gap_status_from_labels(labels: list[str]) -> str | None:
    label_set = set(labels)
    if "resolved" in label_set:
        return "resolved"
    if "gap-scheduled" in label_set:
        return "planned"
    if "open" in label_set:
        return "open"
    return None


def _gap_schedule_from_labels(labels: list[str]) -> str | None:
    for label in labels:
        if label.startswith(_GAP_SCHEDULE_LABEL_PREFIX):
            return label[len(_GAP_SCHEDULE_LABEL_PREFIX) :]
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
            out.append(f"{_GAP_SCHEDULE_LABEL_PREFIX}{lifecycle.gap_schedule}")
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

    if artifact_type == "gap":
        fm_lines.append(f"status: {lifecycle.gap_status or 'open'}")

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


def infer_unit_id(rel_path: str, content: str) -> str:
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            fm = parse_frontmatter_fields(content[: end + 4])
            unit = fm.get("id", "").strip()
            if unit:
                return unit
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
                    unit_id=infer_unit_id(raw, raw),
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
        return f"docs/brainstorms/{unit_id}.md"
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
    try:
        issue_store_visibility_gate(
            root, cfg, artifact.unit_id, artifact.body_path, _visibility_gate_content(artifact)
        )
    except SystemExit:
        return False
    except BaseException:
        return False
    return True


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

    labels = _apply_visibility_label(
        _apply_frozen_labels(
            _apply_gap_labels(
                sorted({project_label(project_key), type_label(artifact.artifact_type)}),
                artifact.lifecycle,
                artifact.artifact_type,
            ),
            artifact.lifecycle,
        ),
        artifact.lifecycle.visibility,
    )
    title = f"{title_prefix(project_key)} {artifact.artifact_type}:{artifact.unit_id}"
    body = compose_issue_body(
        project_key,
        artifact.artifact_type,
        artifact.unit_id,
        artifact.content,
        edges=artifact.lifecycle.edge_list or None,
        native_links=artifact.lifecycle.native_links or None,
    )
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
            native_links=artifact.lifecycle.native_links or None,
        )
    else:
        try:
            record = client.issue_update(
                record.id,
                title=title,
                body=body,
                labels=labels,
                state=artifact.lifecycle.issue_state,
                native_links=artifact.lifecycle.native_links or None,
                if_match=record.etag,
            )
        except IssueRevisionConflict as exc:
            fail(
                "revision-conflict",
                code="revision-conflict",
                expected=exc.expected,
                actual=exc.actual,
            )

    for comment in extra_comments:
        secret_scan_text(comment.body, path_hint=artifact.body_path)
        client.issue_comment(record.id, comment.body, markers=comment.markers)
        record = client.issue_get(record.id)

    if artifact.lifecycle.frozen:
        record = client.issue_lock(record.id, if_match=record.etag)
        record = client.issue_label(record.id, labels, if_match=record.etag)
        snapshot = _record_to_snapshot(record)
        digest = artifact.lifecycle.freeze_hash or canonical_hash(snapshot)
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
        if content_hash(got_content) != artifact.digest:
            return False
        if artifact.lifecycle.frozen and not got_lifecycle.frozen:
            return False
        if artifact.lifecycle.freeze_hash and got_lifecycle.freeze_hash != artifact.lifecycle.freeze_hash:
            return False
        return lifecycle_equal(
            ArtifactLifecycle(
                issue_state=artifact.lifecycle.issue_state,
                frozen=artifact.lifecycle.frozen,
                freeze_hash=got_lifecycle.freeze_hash,
                frozen_at=artifact.lifecycle.frozen_at,
                edge_list=artifact.lifecycle.edge_list,
                native_links=artifact.lifecycle.native_links,
                gap_status=artifact.lifecycle.gap_status,
                gap_schedule=artifact.lifecycle.gap_schedule,
                visibility=artifact.lifecycle.visibility,
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


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Issue-store migration engine")
    parser.add_argument("repo_root")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["migrate", "doctor", "rollback", "scan-quiesce"],
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
    else:
        if not args.direction:
            fail("direction required for migrate")
        run_store_migration(root, args.direction, apply=args.apply)
