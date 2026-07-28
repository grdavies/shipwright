#!/usr/bin/env python3
"""Transition and mutation receipt writer (PRD 081 R25)."""
from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from wave_json_io import read_json, write_json
from wave_run_paths import require_run_id, run_directory
from wave_state import canonical_repo_root

RECEIPTS_DIRNAME = "receipts"
PENDING_SUFFIX = ".pending"


class IncompleteReceiptError(RuntimeError):
    """Raised when a pending receipt blocks resume."""


class ExternalMutationIncompleteError(ValueError):
    """Raised when external mutation receipt preconditions are unmet."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def receipts_directory(root: Path, run_id: str | None) -> Path:
    rid = require_run_id(run_id)
    return run_directory(root, rid) / RECEIPTS_DIRNAME


def _safe_key_fragment(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def receipt_path(root: Path, run_id: str | None, idempotency_key: str) -> Path:
    return receipts_directory(root, run_id) / f"{_safe_key_fragment(idempotency_key)}.json"


def pending_receipt_path(root: Path, run_id: str | None, idempotency_key: str) -> Path:
    final = receipt_path(root, run_id, idempotency_key)
    return final.with_name(final.name + PENDING_SUFFIX)


def hash_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def hash_json(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hash_bytes(canonical.encode("utf-8"))


def revision_record(*, label: str, path: str | None = None, content_hash: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {"label": label}
    if path is not None:
        record["path"] = path
    if content_hash is not None:
        record["hash"] = content_hash
    return record


def compute_idempotency_key(
    run_id: str,
    transition_name: str,
    input_revisions: dict[str, Any],
) -> str:
    payload = {
        "runId": run_id,
        "transitionName": transition_name,
        "inputRevisions": input_revisions,
    }
    return hash_json(payload)


def default_actor() -> str:
    return os.environ.get("SW_RECOVERY_ACTOR") or os.environ.get("USER") or "deliver-loop"


def build_input_revisions(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any] | None,
) -> dict[str, Any]:
    revisions: dict[str, Any] = {
        "state": revision_record(label="state", content_hash=hash_json(state)),
    }
    if plan:
        revisions["plan"] = revision_record(label="plan", content_hash=hash_json(plan))
    run_id = state.get("runId")
    if run_id:
        from wave_run_paths import plan_path, state_path

        anchor = canonical_repo_root(root).resolve()
        revisions["stateFile"] = revision_record(
            label="stateFile",
            path=str(state_path(root, str(run_id)).resolve().relative_to(anchor)),
            content_hash=hash_json(state),
        )
        plan_file = plan_path(root, str(run_id))
        if plan_file.is_file():
            revisions["planFile"] = revision_record(
                label="planFile",
                path=str(plan_file.resolve().relative_to(anchor)),
                content_hash=hash_bytes(plan_file.read_bytes()),
            )
    return revisions


def build_output_revision(state: dict[str, Any]) -> dict[str, Any]:
    return {"state": revision_record(label="state", content_hash=hash_json(state))}


def _write_pending(path: Path, receipt: dict[str, Any]) -> None:
    write_json(path, receipt)


def _finalize_pending(pending_path: Path, final_path: Path, receipt: dict[str, Any]) -> None:
    write_json(final_path, receipt)
    pending_path.unlink(missing_ok=True)


def begin_transition(
    root: Path,
    run_id: str | None,
    transition_name: str,
    *,
    input_revisions: dict[str, Any],
    actor: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    rid = require_run_id(run_id)
    key = idempotency_key or compute_idempotency_key(rid, transition_name, input_revisions)
    final_path = receipt_path(root, rid, key)
    pending_path = pending_receipt_path(root, rid, key)
    if final_path.is_file():
        existing = read_json(final_path, absent_ok=False)
        if existing.get("status") == "complete":
            return existing
    if pending_path.is_file():
        raise IncompleteReceiptError(
            f"transition already pending: {transition_name} ({key})"
        )
    started_at = utc_now()
    receipt: dict[str, Any] = {
        "transitionName": transition_name,
        "idempotencyKey": key,
        "inputRevisions": input_revisions,
        "outputRevision": None,
        "actor": actor or default_actor(),
        "timestamp": started_at,
        "startedAt": started_at,
        "status": "pending",
    }
    _write_pending(pending_path, receipt)
    return receipt


def complete_transition(
    root: Path,
    run_id: str | None,
    idempotency_key: str,
    *,
    output_revision: dict[str, Any],
    actor: str | None = None,
) -> dict[str, Any]:
    rid = require_run_id(run_id)
    pending_path = pending_receipt_path(root, rid, idempotency_key)
    final_path = receipt_path(root, rid, idempotency_key)
    if pending_path.is_file():
        receipt = read_json(pending_path, absent_ok=False)
    elif final_path.is_file():
        receipt = read_json(final_path, absent_ok=False)
        if receipt.get("status") == "complete":
            return receipt
        raise IncompleteReceiptError(f"missing pending receipt for {idempotency_key}")
    else:
        raise IncompleteReceiptError(f"receipt not found for {idempotency_key}")

    completed_at = utc_now()
    receipt.update(
        {
            "outputRevision": output_revision,
            "status": "complete",
            "completedAt": completed_at,
            "timestamp": completed_at,
        }
    )
    if actor:
        receipt["actor"] = actor
    _finalize_pending(pending_path, final_path, receipt)
    return receipt


def fail_transition(
    root: Path,
    run_id: str | None,
    idempotency_key: str,
    *,
    cause: str,
    actor: str | None = None,
) -> dict[str, Any]:
    rid = require_run_id(run_id)
    pending_path = pending_receipt_path(root, rid, idempotency_key)
    final_path = receipt_path(root, rid, idempotency_key)
    if not pending_path.is_file():
        raise IncompleteReceiptError(f"pending receipt missing for {idempotency_key}")
    receipt = read_json(pending_path, absent_ok=False)
    failed_at = utc_now()
    receipt.update(
        {
            "status": "failed",
            "cause": cause,
            "failedAt": failed_at,
            "timestamp": failed_at,
        }
    )
    if actor:
        receipt["actor"] = actor
    _finalize_pending(pending_path, final_path, receipt)
    return receipt


def find_incomplete_receipt(root: Path, run_id: str | None) -> dict[str, Any] | None:
    directory = receipts_directory(root, run_id)
    if not directory.is_dir():
        return None
    for pending in sorted(directory.glob(f"*{PENDING_SUFFIX}")):
        try:
            receipt = read_json(pending, absent_ok=False)
        except Exception:
            continue
        if receipt.get("status") == "pending":
            receipt["path"] = str(pending)
            return receipt
    return None


def resume_incomplete_receipt(root: Path, run_id: str | None) -> dict[str, Any] | None:
    return find_incomplete_receipt(root, run_id)


def read_receipt(root: Path, run_id: str | None, idempotency_key: str) -> dict[str, Any] | None:
    path = receipt_path(root, require_run_id(run_id), idempotency_key)
    if not path.is_file():
        return None
    return read_json(path, absent_ok=False)


def persist_external_mutation_receipt(
    root: Path,
    run_id: str | None,
    transition_name: str,
    *,
    idempotency_key: str,
    input_revisions: dict[str, Any],
    output_revision: dict[str, Any],
    exit_status: int | None,
    remote_state: dict[str, Any] | None,
    actor: str | None = None,
) -> dict[str, Any]:
    if exit_status is None:
        raise ExternalMutationIncompleteError("exit status required for external mutation receipt")
    if remote_state is None:
        raise ExternalMutationIncompleteError("remote state required for external mutation receipt")

    rid = require_run_id(run_id)
    final_path = receipt_path(root, rid, idempotency_key)
    completed_at = utc_now()
    receipt: dict[str, Any] = {
        "transitionName": transition_name,
        "idempotencyKey": idempotency_key,
        "inputRevisions": input_revisions,
        "outputRevision": output_revision,
        "actor": actor or default_actor(),
        "timestamp": completed_at,
        "completedAt": completed_at,
        "status": "failed" if exit_status != 0 else "complete",
        "externalMutation": {
            "exitStatus": exit_status,
            "remoteState": remote_state,
        },
    }
    if exit_status != 0:
        receipt["cause"] = f"external-mutation-exit-{exit_status}"
    write_json(final_path, receipt)
    return receipt


@contextmanager
def mechanical_transition(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any] | None,
    transition_name: str,
) -> Iterator[dict[str, Any] | None]:
    run_id = state.get("runId")
    if not run_id or not transition_name:
        yield None
        return

    incomplete = find_incomplete_receipt(root, str(run_id))
    if incomplete:
        raise IncompleteReceiptError(
            f"incomplete transition {incomplete.get('transitionName')}"
        )

    input_revisions = build_input_revisions(root, state, plan)
    pending = begin_transition(
        root,
        str(run_id),
        transition_name,
        input_revisions=input_revisions,
    )
    key = str(pending["idempotencyKey"])
    failed = True
    try:
        yield pending
        failed = False
    finally:
        if failed:
            try:
                fail_transition(root, str(run_id), key, cause="transition-interrupted")
            except IncompleteReceiptError:
                pass

    complete_transition(
        root,
        str(run_id),
        key,
        output_revision=build_output_revision(state),
    )


TERMINAL_RECEIPT_TRANSITION = "run-finalize"
TERMINAL_RECEIPT_FILENAME = "terminal-receipt.json"


def terminal_receipt_path(root: Path, run_id: str | None) -> Path:
    rid = require_run_id(run_id)
    return run_directory(root, rid) / TERMINAL_RECEIPT_FILENAME


def build_terminal_receipt(
    *,
    merge_commit: str,
    released_resources: dict[str, Any],
    actor: str,
    verified_at: str | None = None,
    merge_detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    completed_at = verified_at or utc_now()
    receipt: dict[str, Any] = {
        "transitionName": TERMINAL_RECEIPT_TRANSITION,
        "status": "complete",
        "mergeCommit": merge_commit,
        "releasedResources": released_resources,
        "actor": actor,
        "timestamp": completed_at,
        "completedAt": completed_at,
    }
    if merge_detail:
        receipt["mergeDetail"] = merge_detail
    return receipt


def persist_terminal_receipt(
    root: Path,
    run_id: str | None,
    receipt: dict[str, Any],
) -> dict[str, Any]:
    rid = require_run_id(run_id)
    path = terminal_receipt_path(root, rid)
    if path.is_file():
        existing = read_json(path, absent_ok=False)
        if existing.get("status") == "complete":
            return existing
    write_json(path, receipt)
    return receipt


def read_terminal_receipt(root: Path, run_id: str | None) -> dict[str, Any] | None:
    path = terminal_receipt_path(root, require_run_id(run_id))
    if not path.is_file():
        return None
    return read_json(path, absent_ok=False)
