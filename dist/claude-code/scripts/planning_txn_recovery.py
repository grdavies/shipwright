#!/usr/bin/env python3
"""Startup recovery replay for planning transaction journals (PRD 082 R28)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from planning_txn import (
    JOURNAL_VERSION,
    JournalCorruptError,
    PlanningTxnCoordinator,
    StagedOp,
    fsync_dir,
    fsync_file,
    journal_path,
    store_lock,
    txn_state_dir,
)


def _validate_journal(doc: dict[str, Any], *, path: Path) -> None:
    if int(doc.get("version", 0)) != JOURNAL_VERSION:
        raise JournalCorruptError(f"unsupported journal version: {path}")
    status = str(doc.get("status") or "")
    if status not in ("pending", "complete"):
        raise JournalCorruptError(f"invalid journal status: {status}")
    ops = doc.get("ops")
    if not isinstance(ops, list) or not ops:
        raise JournalCorruptError(f"journal missing ops: {path}")
    for op in ops:
        if not isinstance(op, dict):
            raise JournalCorruptError(f"journal op must be object: {path}")
        kind = str(op.get("kind") or "")
        if kind not in ("write", "rename"):
            raise JournalCorruptError(f"unknown journal op kind: {kind}")
        if not str(op.get("target") or "").strip():
            raise JournalCorruptError(f"journal op missing target: {path}")
        if kind == "write" and not str(op.get("temp") or "").strip():
            raise JournalCorruptError(f"write op missing temp: {path}")
        if kind == "rename" and not str(op.get("temp") or "").strip():
            raise JournalCorruptError(f"rename op missing source: {path}")


def _ops_from_journal(doc: dict[str, Any]) -> list[StagedOp]:
    ops: list[StagedOp] = []
    for raw in doc.get("ops") or []:
        if not isinstance(raw, dict):
            continue
        ops.append(
            StagedOp(
                kind=str(raw.get("kind") or ""),
                target=str(raw.get("target") or ""),
                temp=str(raw.get("temp") or "") or None,
            )
        )
    return ops


def replay_journal(root: Path, store_id: str, *, doc: dict[str, Any] | None = None) -> dict[str, Any]:
    """Replay one incomplete journal idempotently; corrupt records fail closed."""
    root = root.resolve()
    path = journal_path(root, store_id)
    if doc is None:
        if not path.is_file():
            return {"verdict": "ok", "action": "replay", "storeId": store_id, "note": "no-journal"}
        doc = json.loads(path.read_text(encoding="utf-8"))
    _validate_journal(doc, path=path)
    if str(doc.get("status") or "") == "complete":
        return {"verdict": "ok", "action": "replay", "storeId": store_id, "note": "already-complete"}

    coordinator = PlanningTxnCoordinator(
        root=root,
        store_id=store_id,
        txn_id=str(doc.get("txnId") or ""),
    )
    coordinator._staged = _ops_from_journal(doc)

    with store_lock(root, store_id):
        if not coordinator._staged:
            raise JournalCorruptError("journal has no replayable ops")
        if _journal_already_applied(root, coordinator._staged):
            coordinator._clear_journal()
            return {
                "verdict": "ok",
                "action": "replay",
                "storeId": store_id,
                "note": "idempotent-noop",
            }
        coordinator._apply_staged()
        coordinator._clear_journal()
    return {"verdict": "ok", "action": "replay", "storeId": store_id, "note": "replayed"}


def _journal_already_applied(root: Path, ops: list[StagedOp]) -> bool:
    for op in ops:
        if op.kind == "write":
            target = root / op.target
            temp = Path(op.temp) if op.temp else None
            if temp and temp.is_file():
                return False
            if not target.is_file():
                return False
        if op.kind == "rename":
            source = root / str(op.temp)
            target = root / op.target
            if source.is_file():
                return False
            if not target.is_file():
                return False
    return True


def replay_pending_journals(root: Path, store_id: str | None = None) -> list[dict[str, Any]]:
    """Replay incomplete journals for one store or every store under the txn state dir."""
    root = root.resolve()
    results: list[dict[str, Any]] = []
    if store_id:
        store_ids = [store_id]
    else:
        base = root / ".cursor/hooks/state/planning-txn"
        if not base.is_dir():
            return []
        store_ids = sorted(p.name for p in base.iterdir() if p.is_dir())
    for sid in store_ids:
        path = journal_path(root, sid)
        if not path.is_file():
            continue
        try:
            results.append(replay_journal(root, sid))
        except JournalCorruptError as exc:
            results.append(
                {
                    "verdict": "fail",
                    "action": "replay",
                    "storeId": sid,
                    "error": str(exc),
                }
            )
    return results


def startup_recovery(root: Path) -> dict[str, Any]:
    """Entry point for process startup — replay all pending store journals."""
    results = replay_pending_journals(root)
    failed = [item for item in results if item.get("verdict") == "fail"]
    return {
        "verdict": "fail" if failed else "ok",
        "action": "startup-recovery",
        "results": results,
        "failed": len(failed),
    }
