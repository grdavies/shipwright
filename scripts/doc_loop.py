#!/usr/bin/env python3
"""Durable doc-run driver (PRD 081 R11).

Implements the documented /sw-doc stage sequence with durable run state, idempotent transitions,
and the same machine-readable handshake vocabulary as the deliver loop.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_json_io import read_json, write_json
from wave_target_lock import acquire_doc_run_lock, heartbeat_doc_run_lock, release_doc_run_lock
from wave_transition_receipt import hash_json

DOC_RUNS_DIR_REL = ".cursor/sw-doc-runs"
STATE_FILENAME = "state.json"
INDEX_FILENAME = "index.json"
RECEIPTS_DIRNAME = "receipts"
PENDING_SUFFIX = ".pending"

# Documented /sw-doc stage sequence (tier-gated brainstorm is skipped for non-Full tiers).
DOC_STAGE_SEQUENCE: tuple[str, ...] = (
    "triage",
    "brainstorm",
    "prd",
    "doc-review",
    "freeze-prd",
    "tasks",
    "freeze-tasks",
    "afterTasks-checkpoint",
    "complete",
)

AGENT_STAGES = frozenset({"triage", "brainstorm", "prd", "doc-review", "tasks"})
MECHANICAL_STAGES = frozenset({"freeze-prd", "freeze-tasks"})
HUMAN_STAGES = frozenset({"afterTasks-checkpoint"})
TERMINAL_STAGES = frozenset({"complete"})


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def has_flag(args: list[str], flag: str) -> bool:
    return flag in args


def doc_runs_root(root: Path) -> Path:
    return (root / DOC_RUNS_DIR_REL).resolve()


def doc_run_directory(root: Path, run_id: str) -> Path:
    return doc_runs_root(root) / run_id


def doc_state_path(root: Path, run_id: str) -> Path:
    return doc_run_directory(root, run_id) / STATE_FILENAME


def doc_index_path(root: Path) -> Path:
    return doc_runs_root(root) / INDEX_FILENAME


def doc_receipts_directory(root: Path, run_id: str) -> Path:
    return doc_run_directory(root, run_id) / RECEIPTS_DIRNAME


def doc_receipt_path(root: Path, run_id: str, idempotency_key: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in idempotency_key)
    return doc_receipts_directory(root, run_id) / f"{safe}.json"


def doc_pending_receipt_path(root: Path, run_id: str, idempotency_key: str) -> Path:
    final = doc_receipt_path(root, run_id, idempotency_key)
    return final.with_name(final.name + PENDING_SUFFIX)


def mint_doc_run_id(root: Path) -> str:
    for _ in range(64):
        candidate = f"doc-{uuid.uuid4().hex[:12]}"
        if not doc_run_directory(root, candidate).exists():
            return candidate
    raise RuntimeError("failed to mint unique doc run id")


def input_content_hash(state: dict[str, Any]) -> str:
    payload = {
        "stage": state.get("stage"),
        "tier": state.get("tier"),
        "topic": state.get("topic"),
        "unitIds": state.get("unitIds") or {},
        "artifactRevisions": state.get("artifactRevisions") or {},
        "pendingCheckpoint": state.get("pendingCheckpoint"),
    }
    return hash_json(payload)


def doc_transition_idempotency_key(run_id: str, source_stage: str, content_hash: str) -> str:
    return hash_json(
        {
            "runId": run_id,
            "sourceStage": source_stage,
            "inputContentHash": content_hash,
        }
    )


def read_doc_receipt(root: Path, run_id: str, idempotency_key: str) -> dict[str, Any] | None:
    path = doc_receipt_path(root, run_id, idempotency_key)
    if not path.is_file():
        return None
    return read_json(path, absent_ok=False)


def load_doc_state(root: Path, run_id: str) -> dict[str, Any]:
    return read_json(doc_state_path(root, run_id), absent_ok=False)


def save_doc_state(root: Path, state: dict[str, Any]) -> None:
    run_id = str(state["runId"])
    path = doc_state_path(root, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updatedAt"] = utc_now()
    write_json(path, state)
    update_doc_index(root, state)


def update_doc_index(root: Path, state: dict[str, Any]) -> None:
    index_path = doc_index_path(root)
    index = read_json(index_path, absent_ok=True)
    runs = index.setdefault("runs", {})
    if not isinstance(runs, dict):
        runs = {}
        index["runs"] = runs
    run_id = str(state["runId"])
    runs[run_id] = {
        "runId": run_id,
        "topic": state.get("topic"),
        "tier": state.get("tier"),
        "stage": state.get("stage"),
        "verdict": state.get("verdict"),
        "lockKeyDigest": state.get("lockKeyDigest"),
        "updatedAt": state.get("updatedAt"),
        "createdAt": state.get("createdAt"),
        "statePath": str(doc_state_path(root, run_id).relative_to(root.resolve())),
    }
    index["updatedAt"] = utc_now()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(index_path, index)


def initial_doc_state(
    *,
    run_id: str,
    topic: str,
    tier: str,
    lock_key_digest: str,
) -> dict[str, Any]:
    now = utc_now()
    return {
        "runId": run_id,
        "topic": topic,
        "tier": tier,
        "stage": "triage",
        "verdict": "running",
        "unitIds": {},
        "artifactRevisions": {},
        "pendingCheckpoint": None,
        "lockKeyDigest": lock_key_digest,
        "createdAt": now,
        "updatedAt": now,
        "nextAction": "triage",
    }


def stage_skipped(state: dict[str, Any], stage: str) -> bool:
    tier = str(state.get("tier") or "Standard")
    if stage == "brainstorm" and tier != "Full":
        return True
    return False


def next_stage_after(state: dict[str, Any], current: str) -> str | None:
    if current not in DOC_STAGE_SEQUENCE:
        return None
    idx = DOC_STAGE_SEQUENCE.index(current)
    for candidate in DOC_STAGE_SEQUENCE[idx + 1 :]:
        if stage_skipped(state, candidate):
            continue
        return candidate
    return None


def build_step(state: dict[str, Any], stage: str) -> dict[str, Any]:
    step: dict[str, Any] = {
        "action": stage,
        "stage": stage,
        "runId": state.get("runId"),
        "topic": state.get("topic"),
        "tier": state.get("tier"),
        "resume": state.get("verdict") == "running",
    }
    if stage in HUMAN_STAGES:
        step["checkpoint"] = state.get("pendingCheckpoint") or {
            "kind": "afterTasks-checkpoint",
            "status": "pending",
        }
    return step


def compute_next_action(state: dict[str, Any]) -> dict[str, Any]:
    stage = str(state.get("stage") or "triage")
    if stage in TERMINAL_STAGES:
        return {"action": "complete", "stage": "complete", "runId": state.get("runId")}
    if stage in AGENT_STAGES | MECHANICAL_STAGES | HUMAN_STAGES:
        return build_step(state, stage)
    return build_step(state, "triage")


def apply_recorded_outcome(state: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
    updated = dict(state)
    for key in ("stage", "nextAction", "unitIds", "artifactRevisions", "pendingCheckpoint", "verdict"):
        if key in outcome:
            updated[key] = outcome[key]
    return updated


def record_transition_outcome(
    root: Path,
    run_id: str,
    source_stage: str,
    content_hash: str,
    outcome: dict[str, Any],
) -> dict[str, Any]:
    key = doc_transition_idempotency_key(run_id, source_stage, content_hash)
    final_path = doc_receipt_path(root, run_id, key)
    pending_path = doc_pending_receipt_path(root, run_id, key)
    if final_path.is_file():
        existing = read_json(final_path, absent_ok=False)
        if existing.get("status") == "complete":
            return existing
    receipt: dict[str, Any] = {
        "transitionName": source_stage,
        "idempotencyKey": key,
        "sourceStage": source_stage,
        "inputContentHash": content_hash,
        "outcome": outcome,
        "status": "complete",
        "timestamp": utc_now(),
        "completedAt": utc_now(),
    }
    final_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(final_path, receipt)
    pending_path.unlink(missing_ok=True)
    return receipt


def apply_transition_idempotent(
    root: Path,
    state: dict[str, Any],
    source_stage: str,
    *,
    apply_fn,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    """Apply a transition; return (new_state, receipt, replayed)."""
    run_id = str(state["runId"])
    content_hash = input_content_hash(state)
    key = doc_transition_idempotency_key(run_id, source_stage, content_hash)
    existing = read_doc_receipt(root, run_id, key)
    if existing and existing.get("status") == "complete":
        outcome = existing.get("outcome") or {}
        return apply_recorded_outcome(state, outcome), existing, True
    pending_path = doc_pending_receipt_path(root, run_id, key)
    if pending_path.is_file():
        fail(
            "incomplete doc transition blocks resume",
            exit_code=20,
            halt="doc-loop:incomplete-transition",
            idempotencyKey=key,
        )
    outcome = apply_fn(state)
    receipt = record_transition_outcome(root, run_id, source_stage, content_hash, outcome)
    return apply_recorded_outcome(state, outcome), receipt, False


def advance_stage(state: dict[str, Any], completed_stage: str) -> dict[str, Any]:
    nxt = next_stage_after(state, completed_stage)
    if not nxt:
        return {**state, "stage": "complete", "nextAction": "complete", "verdict": "complete"}
    updated = dict(state)
    updated["stage"] = nxt
    updated["nextAction"] = nxt
    if nxt == "complete":
        updated["verdict"] = "complete"
    return updated


def execute_mechanical_stage(root: Path, state: dict[str, Any], stage: str) -> dict[str, Any]:
    def apply_fn(current: dict[str, Any]) -> dict[str, Any]:
        updated = dict(current)
        revisions = dict(updated.get("artifactRevisions") or {})
        if stage == "freeze-prd":
            revisions["prd"] = {"frozenAt": utc_now(), "revision": revisions.get("prd", {}).get("revision", "draft")}
        elif stage == "freeze-tasks":
            revisions["tasks"] = {
                "frozenAt": utc_now(),
                "revision": revisions.get("tasks", {}).get("revision", "draft"),
            }
        updated["artifactRevisions"] = revisions
        return advance_stage(updated, stage)

    new_state, _receipt, _replayed = apply_transition_idempotent(root, state, stage, apply_fn=apply_fn)
    save_doc_state(root, new_state)
    return {"executed": stage, "stage": new_state.get("stage")}


def consume_agent_stage(
    root: Path,
    state: dict[str, Any],
    stage: str,
    *,
    outcome: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def apply_fn(current: dict[str, Any]) -> dict[str, Any]:
        updated = dict(current)
        if outcome:
            for key in ("unitIds", "artifactRevisions", "tier"):
                if key in outcome:
                    updated[key] = outcome[key]
        return advance_stage(updated, stage)

    new_state, receipt, replayed = apply_transition_idempotent(
        root, state, stage, apply_fn=apply_fn
    )
    if not replayed:
        save_doc_state(root, new_state)
    return {
        "executed": stage,
        "stage": new_state.get("stage"),
        "replayed": replayed,
        "idempotencyKey": receipt.get("idempotencyKey"),
    }


def set_pending_checkpoint(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    checkpoint = {
        "kind": "afterTasks-checkpoint",
        "status": "pending",
        "topic": state.get("topic"),
        "runId": state.get("runId"),
        "emittedAt": utc_now(),
    }
    updated = dict(state)
    updated["pendingCheckpoint"] = checkpoint
    updated["stage"] = "afterTasks-checkpoint"
    updated["nextAction"] = "afterTasks-checkpoint"
    save_doc_state(root, updated)
    return checkpoint


def acknowledge_checkpoint(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    def apply_fn(current: dict[str, Any]) -> dict[str, Any]:
        updated = dict(current)
        checkpoint = dict(updated.get("pendingCheckpoint") or {})
        checkpoint["status"] = "acknowledged"
        checkpoint["acknowledgedAt"] = utc_now()
        updated["pendingCheckpoint"] = checkpoint
        return advance_stage(updated, "afterTasks-checkpoint")

    new_state, _receipt, replayed = apply_transition_idempotent(
        root, state, "afterTasks-checkpoint", apply_fn=apply_fn
    )
    save_doc_state(root, new_state)
    return {"executed": "afterTasks-checkpoint", "replayed": replayed, "stage": new_state.get("stage")}


def provision_doc_run(
    root: Path,
    *,
    topic: str,
    tier: str = "Standard",
    run_id: str | None = None,
) -> dict[str, Any]:
    """Acquire doc-run lock then create run directory (lock precedes run dir — R11)."""
    rid = run_id or mint_doc_run_id(root)
    lock = acquire_doc_run_lock(root, topic, rid)
    if lock.get("verdict") != "pass":
        return lock
    if doc_run_directory(root, rid).exists():
        return {
            "verdict": "fail",
            "error": "doc-run-directory-exists",
            "runId": rid,
        }
    state = initial_doc_state(
        run_id=rid,
        topic=topic,
        tier=tier,
        lock_key_digest=str(lock.get("lockKeyDigest") or ""),
    )
    save_doc_state(root, state)
    heartbeat_doc_run_lock(root, topic, rid)
    return {
        "verdict": "pass",
        "action": "doc-run-provision",
        "runId": rid,
        "topic": topic,
        "tier": tier,
        "lockKeyDigest": lock.get("lockKeyDigest"),
        "statePath": str(doc_state_path(root, rid)),
    }


def resolve_run_id(root: Path, args: list[str]) -> str:
    run_id = (
        parse_kv(args, "--run-id")
        or os.environ.get("SW_DOC_RUN_ID", "").strip()
        or ""
    )
    if run_id:
        return run_id
    topic = parse_kv(args, "--topic")
    if topic:
        provisioned = provision_doc_run(
            root,
            topic=topic,
            tier=parse_kv(args, "--tier", "Standard") or "Standard",
        )
        if provisioned.get("verdict") != "pass":
            fail(provisioned.get("error", "doc run provision failed"), **provisioned)
        return str(provisioned["runId"])
    fail("--run-id or --topic required")


def handshake_payload(
    *,
    state: dict[str, Any],
    step: dict[str, Any],
    resumed: bool,
    steps_taken: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    stage = str(step.get("stage") or step.get("action") or "")
    if stage in HUMAN_STAGES and state.get("pendingCheckpoint"):
        step = {**step, "checkpoint": state.get("pendingCheckpoint")}
    payload: dict[str, Any] = {
        "verdict": "pass",
        "action": "doc-loop",
        "resumed": resumed,
        "awaitAgent": stage in AGENT_STAGES,
        "awaitHuman": stage in HUMAN_STAGES,
        "next": step,
        "stepsTaken": steps_taken or [],
        **extra,
    }
    if stage in TERMINAL_STAGES:
        payload["terminal"] = True
        payload["runVerdict"] = state.get("verdict")
    return payload


def cmd_doc_loop(root: Path, args: list[str]) -> None:
    dry_run = has_flag(args, "--dry-run")
    consume = has_flag(args, "--consume")
    ack_checkpoint = has_flag(args, "--ack-checkpoint")
    max_steps = int(parse_kv(args, "--max-steps", "8") or "8")
    run_id = resolve_run_id(root, args)
    state = load_doc_state(root, run_id)
    resumed = bool(state.get("verdict") == "running" and state.get("stage") != "triage")
    steps_taken: list[dict[str, Any]] = []

    for _ in range(max_steps):
        state = load_doc_state(root, run_id)
        step = compute_next_action(state)
        stage = str(step.get("stage") or step.get("action") or "")

        if dry_run:
            emit(handshake_payload(state=state, step=step, resumed=resumed, dry_run=True))

        if stage in TERMINAL_STAGES:
            emit(
                handshake_payload(
                    state=state,
                    step=step,
                    resumed=resumed,
                    stepsTaken=steps_taken,
                    complete=True,
                )
            )

        if stage in HUMAN_STAGES:
            checkpoint = state.get("pendingCheckpoint")
            if not checkpoint:
                checkpoint = set_pending_checkpoint(root, state)
                state = load_doc_state(root, run_id)
            if ack_checkpoint:
                result = acknowledge_checkpoint(root, state)
                steps_taken.append(result)
                resumed = True
                continue
            emit(
                handshake_payload(
                    state=state,
                    step={**step, "checkpoint": checkpoint},
                    resumed=resumed,
                    stepsTaken=steps_taken,
                    halt=False,
                )
            )

        if stage in AGENT_STAGES:
            if consume:
                agent_outcome_raw = parse_kv(args, "--outcome")
                outcome: dict[str, Any] | None = None
                if agent_outcome_raw:
                    outcome = json.loads(agent_outcome_raw)
                result = consume_agent_stage(root, state, stage, outcome=outcome)
                steps_taken.append(result)
                resumed = True
                continue
            emit(handshake_payload(state=state, step=step, resumed=resumed, stepsTaken=steps_taken))

        if stage in MECHANICAL_STAGES:
            result = execute_mechanical_stage(root, state, stage)
            steps_taken.append(result)
            resumed = True
            continue

        fail(f"unhandled doc stage: {stage}", step=step)

    state = load_doc_state(root, run_id)
    next_step = compute_next_action(state)
    emit(
        handshake_payload(
            state=state,
            step=next_step,
            resumed=resumed,
            stepsTaken=steps_taken,
            note=f"step budget ({max_steps}) reached",
        )
    )


def cmd_release(root: Path, args: list[str]) -> None:
    run_id = parse_kv(args, "--run-id") or os.environ.get("SW_DOC_RUN_ID", "")
    if not run_id:
        fail("--run-id required")
    state = load_doc_state(root, run_id)
    topic = str(state.get("topic") or "")
    if not topic:
        fail("doc state missing topic")
    out = release_doc_run_lock(root, topic, run_id)
    if out.get("verdict") != "pass":
        fail(out.get("error", "doc-run lock release failed"), **out)
    emit(out)


def main() -> None:
    if len(sys.argv) < 2:
        fail("usage: doc_loop.py <root> <doc-loop|release> ...")
    root = Path(sys.argv[1]).resolve()
    cmd = sys.argv[2] if len(sys.argv) > 2 else "doc-loop"
    rest = sys.argv[3:]
    if cmd == "doc-loop":
        cmd_doc_loop(root, rest)
    elif cmd == "release":
        cmd_release(root, rest)
    else:
        fail(f"unknown doc-loop subcommand: {cmd}")


if __name__ == "__main__":
    main()
