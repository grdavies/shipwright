"""Issue-store index/journal helpers (PRD 082 phase 12 / R27)."""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

ISSUE_UNIT_INDEX = ".cursor/hooks/state/issue-store-unit-index.json"
PUT_JOURNAL_PATH = ".cursor/hooks/state/issue-store-put-journal.json"
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
