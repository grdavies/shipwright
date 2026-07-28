"""Store migration hooks and operators (PRD 082 phase 11 / R27)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

ISSUES_MIGRATION_HOOKS: tuple[str, ...] = (
    "scripts/planning_migrate_issue_store.py",
    "scripts/planning_migrate.py",
)

ORPHAN_MIGRATED_LABEL = "sw:phase-orphan-migrated"


def migrate_orphan_phase_issues(
    root: Path,
    cfg: dict[str, Any] | None = None,
    *,
    tasks_unit_id: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Close/relabel pre-061 minted phase peer issues; idempotent (PRD 061 R8a)."""
    from host_lib import load_workflow_config
    from issues_lib import IssuesClient
    from .identity import validate_project_key
    from planning_store import resolve_effective_backend, resolve_issues_provider

    cfg = cfg or load_workflow_config(root)
    if resolve_effective_backend(root, cfg).get("effective") != "issue-store":
        return {"verdict": "ok", "skipped": True, "reason": "file-store"}
    pk = validate_project_key(root, cfg)
    if pk.get("verdict") != "ok":
        return pk
    project_key = str(pk["projectKey"])
    provider = str(resolve_issues_provider(cfg).get("provider") or "none")
    client = IssuesClient(root, provider)
    search = getattr(client, "issue_search", None)
    if not callable(search):
        return {"verdict": "ok", "skipped": True, "reason": "issue-search-unavailable"}

    migrated: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    prefix = f"{tasks_unit_id}-phase-" if tasks_unit_id else None
    for record in search(project_key=project_key, artifact_type="tasks"):
        unit_id = str(getattr(record, "unit_id", "") or "")
        if prefix and not unit_id.startswith(prefix):
            continue
        if not prefix and "-phase-" not in unit_id:
            continue
        labels = list(getattr(record, "labels", []))
        if ORPHAN_MIGRATED_LABEL in labels:
            skipped.append({"unitId": unit_id, "reason": "already-migrated"})
            continue
        issue_id = str(getattr(record, "id", "") or "")
        if dry_run:
            migrated.append({"unitId": unit_id, "issueId": issue_id, "dryRun": True})
            continue
        new_labels = sorted(set(labels) | {ORPHAN_MIGRATED_LABEL})
        try:
            client.issue_label(issue_id, new_labels, if_match=getattr(record, "etag", None))
            if getattr(record, "state", "open") == "open":
                client.issue_update(issue_id, state="closed")
            migrated.append({"unitId": unit_id, "issueId": issue_id})
        except Exception as exc:  # noqa: BLE001
            skipped.append({"unitId": unit_id, "reason": str(exc)})
    return {
        "verdict": "ok",
        "action": "migrate-orphan-phase-issues",
        "dryRun": dry_run,
        "migrated": migrated,
        "skipped": skipped,
        "count": len(migrated),
    }
