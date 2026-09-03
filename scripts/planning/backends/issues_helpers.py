"""Issue-store index/journal helpers (PRD 082 phase 12 / R27)."""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

ISSUE_UNIT_INDEX = ".cursor/hooks/state/issue-store-unit-index.json"
PUT_JOURNAL_PATH = ".cursor/hooks/state/issue-store-put-journal.json"
ISSUE_UNIT_INDEX_AUDIT = ".cursor/hooks/state/issue-store-unit-index-audit.jsonl"
ISSUE_STORE_TXN_ID = "issue-store"

def load_issue_unit_index(root: Path) -> dict[str, str]:
    path = root / ISSUE_UNIT_INDEX
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    units = data.get("units") if isinstance(data, dict) else None
    if not isinstance(units, dict):
        return {}
    return {str(k): str(v) for k, v in units.items() if isinstance(k, str) and isinstance(v, str)}


def _issue_index_payload(index: dict[str, str]) -> str:
    return json.dumps({"version": 1, "units": index}, indent=2) + "\n"


def _put_journal_payload(journal: dict[str, Any]) -> str:
    return (
        json.dumps({"version": 1, "units": journal}, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )


def save_issue_unit_index(root: Path, index: dict[str, str]) -> None:
    from planning_txn import planning_transaction

    path = root / ISSUE_UNIT_INDEX
    with planning_transaction(root, ISSUE_STORE_TXN_ID) as txn:
        txn.stage_write(path, _issue_index_payload(index))


def mutate_issue_unit_index(root: Path, mutator: Callable[[dict[str, str]], None]) -> None:
    from planning_txn import planning_transaction

    path = root / ISSUE_UNIT_INDEX
    with planning_transaction(root, ISSUE_STORE_TXN_ID) as txn:
        index = load_issue_unit_index(root)
        mutator(index)
        txn.stage_write(path, _issue_index_payload(index))


def issue_index_key(project_key: str, unit_id: str) -> str:
    return f"{project_key}:{unit_id}"


def read_issue_unit_index_locked(root: Path) -> dict[str, str]:
    from planning_txn import store_lock

    with store_lock(root, ISSUE_STORE_TXN_ID):
        return load_issue_unit_index(root)


def read_put_journal_locked(root: Path) -> dict[str, Any]:
    from planning_txn import store_lock

    with store_lock(root, ISSUE_STORE_TXN_ID):
        return load_put_journal(root)


def load_put_journal(root: Path) -> dict[str, Any]:
    """R26 -- load the partial-write journal (keyed by ``issue_index_key``)."""
    path = root / PUT_JOURNAL_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    entries = data.get("units") if isinstance(data, dict) else None
    return entries if isinstance(entries, dict) else {}


def save_put_journal(root: Path, journal: dict[str, Any]) -> None:
    from planning_txn import planning_transaction

    path = root / PUT_JOURNAL_PATH
    with planning_transaction(root, ISSUE_STORE_TXN_ID) as txn:
        txn.stage_write(path, _put_journal_payload(journal))


def mutate_put_journal(root: Path, mutator: Callable[[dict[str, Any]], None]) -> None:
    from planning_txn import planning_transaction

    path = root / PUT_JOURNAL_PATH
    with planning_transaction(root, ISSUE_STORE_TXN_ID) as txn:
        journal = load_put_journal(root)
        mutator(journal)
        txn.stage_write(path, _put_journal_payload(journal))


def append_unit_index_audit(root: Path, entry: dict[str, Any]) -> None:
    """Append-only audit for unit-index mutations (PRD 339 R39)."""
    from datetime import datetime, timezone

    path = root / ISSUE_UNIT_INDEX_AUDIT
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **entry,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")


def self_heal_issue_unit_index(
    root: Path,
    *,
    project_key: str,
    resolve_record: Callable[[str], Any | None],
    record_unit_id: Callable[[Any], str],
    record_artifact_type: Callable[[Any], str],
) -> dict[str, Any]:
    """Heal polluted unit-index entries via single-writer CAS (PRD 339 R39).

    Drops entries whose issue is missing, out of project scope, or whose
    recorded unit-id no longer matches the index key. Concurrent writers share
    ``planning_transaction`` / store lock — no silent dual-writer overwrite.
    """
    from planning_txn import planning_transaction

    path = root / ISSUE_UNIT_INDEX
    removed: list[dict[str, str]] = []
    with planning_transaction(root, ISSUE_STORE_TXN_ID) as txn:
        index = load_issue_unit_index(root)
        prefix = f"{project_key}:"
        for key, issue_id in list(index.items()):
            if not key.startswith(prefix):
                continue
            unit_id = key[len(prefix) :]
            record = resolve_record(issue_id)
            if record is None:
                del index[key]
                removed.append({"key": key, "issueId": issue_id, "reason": "missing-issue"})
                continue
            got_unit = record_unit_id(record)
            if got_unit and got_unit != unit_id:
                del index[key]
                removed.append(
                    {
                        "key": key,
                        "issueId": issue_id,
                        "reason": "unit-id-mismatch",
                        "recordUnitId": got_unit,
                    }
                )
                continue
            # artifact type is informational for heal; marker reuse refusal owns type clashes
            _ = record_artifact_type(record)
        if removed:
            txn.stage_write(path, _issue_index_payload(index))
    for item in removed:
        append_unit_index_audit(
            root,
            {"event": "unit-index-self-heal", "projectKey": project_key, **item},
        )
    return {
        "verdict": "pass",
        "action": "unit-index-self-heal",
        "removed": removed,
        "removedCount": len(removed),
    }


def record_artifact_type(record: Any, *, ps_mod: Any) -> str:
    content = ps_mod.strip_markers_and_edges(ps_mod.reassemble_body(record.body, record.comments))
    return (
        str(getattr(record, "artifact_type", "") or "").strip()
        or ps_mod.artifact_type_from_labels(list(getattr(record, "labels", []) or []))
        or ps_mod.artifact_type_from_content(content)
        or ""
    )


def record_unit_id(record: Any, *, ps_mod: Any, unit_marker: Any) -> str:
    labels = list(getattr(record, "labels", []) or [])
    from_labels = ps_mod.unit_id_from_labels(labels)
    if from_labels:
        return from_labels
    raw = str(getattr(record, "unit_id", "") or "").strip()
    if raw:
        return raw
    body = getattr(record, "body", "") or ""
    match = unit_marker.search(body)
    return match.group(1).strip() if match else ""


def guard_unit_id_marker_reuse(
    *,
    unit_id: str,
    artifact_type: str,
    existing: Any | None,
    project_key: str,
    client: Any,
    fail_fn: Callable[..., None],
    ps_mod: Any,
    unit_marker: Any,
) -> None:
    """PRD 339 R39 — refuse sw-unit-id marker reuse across artifact types."""

    def _refuse(match: Any, match_type: str) -> None:
        fail_fn(
            "unit-id-marker-reuse",
            code="unit-id-marker-reuse",
            unitId=unit_id,
            existingArtifactType=match_type,
            requestedArtifactType=artifact_type,
            issueId=str(getattr(match, "id", "") or ""),
        )

    if existing is not None:
        existing_type = record_artifact_type(existing, ps_mod=ps_mod)
        if existing_type and existing_type != artifact_type:
            _refuse(existing, existing_type)

    search = getattr(client, "issue_search", None)
    if not callable(search):
        return
    matches = client.issue_search(project_key=project_key, unit_id=unit_id)
    for match in matches or []:
        if existing is not None and str(getattr(match, "id", "")) == str(getattr(existing, "id", "")):
            continue
        match_type = record_artifact_type(match, ps_mod=ps_mod)
        if match_type and match_type != artifact_type:
            _refuse(match, match_type)
