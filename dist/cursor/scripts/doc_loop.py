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
from wave_run_paths import RunIdRequiredError, require_run_id
from wave_target_lock import (
    acquire_doc_run_lock,
    heartbeat_doc_run_lock,
    release_doc_run_lock,
    release_doc_run_lock_on_terminal_complete,
)
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
    "related-work",
    "final-triage-rescore",
    "freeze-prd",
    "tasks",
    "freeze-tasks",
    "afterTasks-checkpoint",
    "feature-seed",
    "complete",
)

AGENT_STAGES = frozenset({"triage", "brainstorm", "prd", "doc-review", "final-triage-rescore", "tasks"})
MECHANICAL_STAGES = frozenset({"related-work", "freeze-prd", "freeze-tasks", "feature-seed"})
HUMAN_STAGES = frozenset({"related-work-checkpoint", "afterTasks-checkpoint"})
TERMINAL_STAGES = frozenset({"complete"})
UNREACHABLE_PUBLICATION_STAGES = frozenset({"docs-commit", "docs-pr"})


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
    """Resolve doc-run namespace under the primary repo-root .cursor (R8)."""
    from wave_state import path_normalize_anchor

    return (path_normalize_anchor(root) / DOC_RUNS_DIR_REL).resolve()


def doc_run_directory(root: Path, run_id: str) -> Path:
    rid = require_run_id(run_id)
    return doc_runs_root(root) / rid


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
        "artifactPaths": state.get("artifactPaths") or {},
        "pendingCheckpoint": state.get("pendingCheckpoint"),
        "pendingRelatedWork": state.get("pendingRelatedWork"),
        "relatedWorkScan": state.get("relatedWorkScan"),
        "rescoreReceipt": state.get("rescoreReceipt"),
        "proposedTier": state.get("proposedTier"),
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
    if stage == "tasks":
        step["noFreeze"] = True
    if stage == "related-work-checkpoint":
        step["checkpoint"] = state.get("pendingRelatedWork") or {
            "kind": "related-work-checkpoint",
            "status": "pending",
        }
    elif stage in HUMAN_STAGES:
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
    for key in (
        "stage",
        "nextAction",
        "unitIds",
        "artifactPaths",
        "artifactRevisions",
        "pendingCheckpoint",
        "pendingRelatedWork",
        "relatedWorkScan",
        "verdict",
        "halt",
        "haltError",
        "haltReceipt",
        "featureSeedReceipt",
        "rescoreReceipt",
        "proposedTier",
        "tier",
    ):
        if key in outcome:
            updated[key] = outcome[key]
    return updated


def apply_final_triage_rescore(root: Path, state: dict[str, Any], outcome: dict[str, Any] | None) -> dict[str, Any]:
    from doc_rescore import evaluate_rescore

    payload = outcome or {}
    proposed_tier = payload.get("proposedTier") or payload.get("tier") or state.get("proposedTier")
    if not proposed_tier:
        return {
            "verdict": "fail",
            "error": "missing-proposed-tier",
            "halt": "doc-loop:rescore-input",
        }
    prd_frozen = bool((state.get("artifactRevisions") or {}).get("prd", {}).get("lifecycleState") == "frozen")
    result = evaluate_rescore(
        current_tier=str(state.get("tier") or "Standard"),
        proposed_tier=str(proposed_tier),
        frozen=prd_frozen,
        justification=payload.get("justification"),
        actor=payload.get("actor"),
        unit_id=str((state.get("unitIds") or {}).get("prd") or ""),
        signals=payload.get("signals") if isinstance(payload.get("signals"), dict) else None,
        root=root,
    )
    if result.get("verdict") != "pass":
        return result
    updated: dict[str, Any] = {
        "verdict": "pass",
        "rescoreReceipt": result.get("receipt"),
        "proposedTier": proposed_tier,
    }
    applied = str(result.get("appliedTier") or state.get("tier") or "Standard")
    updated["tier"] = applied
    if result.get("requiresBrainstorm"):
        updated["stage"] = "brainstorm"
        updated["nextAction"] = "brainstorm"
        return updated
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


def finalize_doc_run_terminal(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Release the topic doc-run lock when the run reaches terminal ``complete`` (R9)."""
    topic = str(state.get("topic") or "")
    run_id = str(state.get("runId") or "")
    if not topic or not run_id:
        return {"verdict": "fail", "error": "doc-state-missing-topic-or-run-id"}
    if str(state.get("stage") or "") != "complete" or state.get("verdict") != "complete":
        return {"verdict": "skip", "note": "not-terminal-complete"}
    return release_doc_run_lock_on_terminal_complete(root, topic, run_id)


def artifact_rel_path(state: dict[str, Any], key: str) -> str | None:
    paths = state.get("artifactPaths") or {}
    rel = paths.get(key)
    if isinstance(rel, str) and rel.strip():
        return rel.strip()
    unit_ids = state.get("unitIds") or {}
    unit_id = unit_ids.get(key)
    if not isinstance(unit_id, str) or not unit_id.strip():
        return None
    topic = str(state.get("topic") or "topic")
    if key == "prd":
        return f"docs/prds/{unit_id}/prd.md"
    if key == "tasks":
        return f"docs/prds/{unit_id}/tasks-{unit_id.split('-prd-', 1)[-1] if '-prd-' in unit_id else unit_id}.md"
    return None


def artifacts_are_durable(state: dict[str, Any]) -> bool:
    revisions = state.get("artifactRevisions") or {}
    for key in ("prd", "tasks"):
        record = revisions.get(key) or {}
        if record.get("durabilityState") != "verified":
            return False
    return True


def deliver_handoff_reachable(state: dict[str, Any]) -> bool:
    if state.get("verdict") == "halted":
        return False
    if not artifacts_are_durable(state):
        return False
    related = state.get("pendingRelatedWork") or {}
    if related.get("status") == "pending":
        return False
    if not state.get("featureSeedReceipt") and str(state.get("stage") or "") != "complete":
        return False
    return str(state.get("stage") or "") in {"complete"}


def assert_publication_stage_reachable(stage: str) -> None:
    if stage in UNREACHABLE_PUBLICATION_STAGES:
        fail(
            f"publication stage {stage!r} is unreachable from doc-loop driver",
            exit_code=20,
            halt="doc-loop:publication-cutover",
            stage=stage,
        )


def publication_mode(root: Path) -> str:
    from planning_artifact_handle import issue_store_separate_project_effective

    if issue_store_separate_project_effective(root):
        return "separate-project-store-only"
    return "file-store-feature-seed"


def run_feature_seed(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    mode = publication_mode(root)
    tasks_rel = artifact_rel_path(state, "tasks")
    if not tasks_rel:
        return {
            "verdict": "fail",
            "error": "missing-tasks-path",
            "halt": "doc-loop:missing-artifact",
        }

    if mode == "separate-project-store-only":
        return {
            "verdict": "pass",
            "action": "feature-seed",
            "skipped": True,
            "reason": "separate-project-store-only",
            "publicationMode": mode,
            "note": "no local publication; deliver run-entry materialize supplies content",
        }

    prd_rel = artifact_rel_path(state, "prd")
    if prd_rel:
        import doc_link

        check = doc_link.check_artifact(root, prd_rel, tier="full")
        if check.get("verdict") != "pass":
            return {
                "verdict": "fail",
                "error": "brainstorm-reference-unresolved",
                "halt": "doc-loop:brainstorm-reference",
                "check": check,
            }

    import subprocess

    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "wave_spec_seed.py"),
            str(root),
            "spec-seed",
            "--task-list",
            tasks_rel,
            "--run-id",
            f"doc-loop:{state.get('runId')}",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    remote_state = {"branch": None, "commit": None, "dryRun": True}
    try:
        seed_payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        seed_payload = {"verdict": "fail", "detail": proc.stdout or proc.stderr}
    exit_status = proc.returncode
    if exit_status != 0:
        return {
            "verdict": "fail",
            "error": seed_payload.get("error") or "feature-seed-failed",
            "halt": "doc-loop:feature-seed",
            "exitStatus": exit_status,
            "seed": seed_payload,
        }

    receipt = {
        "transitionName": "feature-seed",
        "publicationMode": mode,
        "exitStatus": exit_status,
        "remoteState": remote_state,
        "seed": seed_payload,
        "timestamp": utc_now(),
        "status": "complete",
    }
    return {
        "verdict": "pass",
        "action": "feature-seed",
        "publicationMode": mode,
        "receipt": receipt,
        "seed": seed_payload,
    }


def run_related_work_scan(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    import planning_related

    prd_path = artifact_rel_path(state, "prd")
    if not prd_path:
        return {"verdict": "ok", "proposals": [], "skipped": True, "reason": "missing-prd-path"}
    os.environ["SW_DOC_DRIVER"] = "1"
    return planning_related.scan_related(
        root,
        planning_related.source_from_path(root, prd_path),
        mode="tasks-rescan",
    )


def freeze_stage_artifact(root: Path, state: dict[str, Any], stage: str) -> dict[str, Any]:
    from check_frozen_lib import freeze_artifact

    key = "prd" if stage == "freeze-prd" else "tasks"
    rel = artifact_rel_path(state, key)
    if not rel:
        return {
            "verdict": "fail",
            "error": "missing-artifact-path",
            "artifactKey": key,
            "halt": "doc-loop:missing-artifact",
        }
    unit_ids = state.get("unitIds") or {}
    owner = f"doc-loop:{state.get('runId')}"
    receipt = freeze_artifact(
        root,
        rel,
        owner=owner,
        driver_invoked=True,
        unit_id=str(unit_ids.get(key) or ""),
    )
    if receipt.get("verdict") == "fail":
        return {
            "verdict": "fail",
            "error": receipt.get("error") or "freeze-durability-failed",
            "halt": "doc-loop:freeze-durability",
            "receipt": receipt,
        }
    return {"verdict": "pass", "receipt": receipt, "artifactKey": key}


def execute_mechanical_stage(root: Path, state: dict[str, Any], stage: str) -> dict[str, Any]:
    def apply_fn(current: dict[str, Any]) -> dict[str, Any]:
        updated = dict(current)
        if stage == "related-work":
            scan = run_related_work_scan(root, updated)
            updated["relatedWorkScan"] = scan
            proposals = scan.get("proposals") or []
            if proposals:
                updated["pendingRelatedWork"] = {
                    "kind": "related-work-checkpoint",
                    "status": "pending",
                    "proposals": proposals,
                    "emittedAt": utc_now(),
                }
                updated["stage"] = "related-work-checkpoint"
                updated["nextAction"] = "related-work-checkpoint"
                return updated
            updated["pendingRelatedWork"] = {
                "kind": "related-work-checkpoint",
                "status": "acknowledged",
                "proposals": [],
                "emittedAt": utc_now(),
            }
            return advance_stage(updated, stage)

        if stage in {"freeze-prd", "freeze-tasks"}:
            outcome = freeze_stage_artifact(root, updated, stage)
            if outcome.get("verdict") != "pass":
                updated["verdict"] = "halted"
                updated["halt"] = outcome.get("halt")
                updated["haltError"] = outcome.get("error")
                updated["haltReceipt"] = outcome.get("receipt")
                return updated
            revisions = dict(updated.get("artifactRevisions") or {})
            receipt = outcome.get("receipt") or {}
            key = str(outcome.get("artifactKey") or "")
            revisions[key] = {
                **receipt,
                "frozenAt": utc_now(),
            }
            updated["artifactRevisions"] = revisions
            return advance_stage(updated, stage)

        if stage == "feature-seed":
            outcome = run_feature_seed(root, updated)
            if outcome.get("verdict") != "pass":
                updated["verdict"] = "halted"
                updated["halt"] = outcome.get("halt")
                updated["haltError"] = outcome.get("error")
                updated["haltReceipt"] = outcome.get("receipt")
                return updated
            updated["featureSeedReceipt"] = outcome.get("receipt") or outcome
            return advance_stage(updated, stage)

        return advance_stage(updated, stage)

    new_state, _receipt, _replayed = apply_transition_idempotent(root, state, stage, apply_fn=apply_fn)
    save_doc_state(root, new_state)
    result: dict[str, Any] = {"executed": stage, "stage": new_state.get("stage")}
    if new_state.get("verdict") == "halted":
        result["halted"] = True
        result["halt"] = new_state.get("halt")
        result["deliverHandoffReachable"] = deliver_handoff_reachable(new_state)
    if new_state.get("stage") == "complete" and new_state.get("verdict") == "complete":
        result["lockRelease"] = finalize_doc_run_terminal(root, new_state)
    return result


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
            for key in ("unitIds", "artifactRevisions", "tier", "proposedTier", "artifactPaths"):
                if key in outcome:
                    updated[key] = outcome[key]
        if stage == "final-triage-rescore":
            rescore = apply_final_triage_rescore(root, updated, outcome)
            if rescore.get("verdict") != "pass":
                updated["verdict"] = "halted"
                updated["halt"] = rescore.get("halt") or "doc-loop:rescore-policy"
                updated["haltError"] = rescore.get("error")
                updated["haltReceipt"] = rescore.get("receipt")
                return updated
            updated.update(
                {
                    key: value
                    for key, value in rescore.items()
                    if key in {"rescoreReceipt", "proposedTier", "tier", "stage", "nextAction"}
                }
            )
            if updated.get("stage") == "brainstorm":
                return updated
        return advance_stage(updated, stage)

    new_state, receipt, replayed = apply_transition_idempotent(
        root, state, stage, apply_fn=apply_fn
    )
    if not replayed:
        save_doc_state(root, new_state)
    result = {
        "executed": stage,
        "stage": new_state.get("stage"),
        "replayed": replayed,
        "idempotencyKey": receipt.get("idempotencyKey"),
    }
    if new_state.get("verdict") == "halted":
        result["halted"] = True
        result["halt"] = new_state.get("halt")
    return result


def set_pending_checkpoint(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    if not artifacts_are_durable(state):
        fail(
            "checkpoint blocked until freeze durability verified for prd and tasks",
            exit_code=20,
            halt="doc-loop:freeze-durability-pending",
            deliverHandoffReachable=False,
        )
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


def acknowledge_related_work(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    def apply_fn(current: dict[str, Any]) -> dict[str, Any]:
        updated = dict(current)
        pending = dict(updated.get("pendingRelatedWork") or {})
        pending["status"] = "acknowledged"
        pending["acknowledgedAt"] = utc_now()
        updated["pendingRelatedWork"] = pending
        return advance_stage(updated, "related-work")

    new_state, _receipt, replayed = apply_transition_idempotent(
        root, state, "related-work-checkpoint", apply_fn=apply_fn
    )
    save_doc_state(root, new_state)
    return {
        "executed": "related-work-checkpoint",
        "replayed": replayed,
        "stage": new_state.get("stage"),
    }


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
    if run_id:
        try:
            rid = require_run_id(run_id)
        except RunIdRequiredError as exc:
            return {"verdict": "fail", "error": str(exc), "runId": run_id}
    else:
        rid = mint_doc_run_id(root)
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
        try:
            return require_run_id(run_id)
        except RunIdRequiredError as exc:
            fail(str(exc), exit_code=20, halt="doc-run-id-invalid")
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
    if stage == "related-work-checkpoint" and state.get("pendingRelatedWork"):
        step = {**step, "checkpoint": state.get("pendingRelatedWork")}
    elif stage in HUMAN_STAGES and state.get("pendingCheckpoint"):
        step = {**step, "checkpoint": state.get("pendingCheckpoint")}
    payload: dict[str, Any] = {
        "verdict": "pass",
        "action": "doc-loop",
        "resumed": resumed,
        "awaitAgent": stage in AGENT_STAGES,
        "awaitHuman": stage in HUMAN_STAGES,
        "next": step,
        "stepsTaken": steps_taken or [],
        "deliverHandoffReachable": deliver_handoff_reachable(state),
        **extra,
    }
    if state.get("verdict") == "halted":
        payload["halt"] = True
        payload["haltCause"] = state.get("halt")
    if stage in TERMINAL_STAGES:
        payload["terminal"] = True
        payload["runVerdict"] = state.get("verdict")
    return payload


def cmd_doc_loop(root: Path, args: list[str]) -> None:
    dry_run = has_flag(args, "--dry-run")
    consume = has_flag(args, "--consume")
    ack_checkpoint = has_flag(args, "--ack-checkpoint")
    ack_related_work = has_flag(args, "--ack-related-work")
    max_steps = int(parse_kv(args, "--max-steps", "8") or "8")
    publication_stage = parse_kv(args, "--publication-stage")
    if publication_stage:
        assert_publication_stage_reachable(publication_stage)
    run_id = resolve_run_id(root, args)
    state = load_doc_state(root, run_id)
    resumed = bool(state.get("verdict") == "running" and state.get("stage") != "triage")
    steps_taken: list[dict[str, Any]] = []

    for _ in range(max_steps):
        state = load_doc_state(root, run_id)
        if state.get("verdict") == "halted":
            emit(
                handshake_payload(
                    state=state,
                    step={"action": state.get("stage"), "stage": state.get("stage"), "runId": run_id},
                    resumed=resumed,
                    steps_taken=steps_taken,
                    halt=True,
                ),
                exit_code=20,
            )
        step = compute_next_action(state)
        stage = str(step.get("stage") or step.get("action") or "")

        if dry_run:
            emit(handshake_payload(state=state, step=step, resumed=resumed, dry_run=True))

        if stage in TERMINAL_STAGES:
            lock_release = finalize_doc_run_terminal(root, state)
            emit(
                handshake_payload(
                    state=state,
                    step=step,
                    resumed=resumed,
                    stepsTaken=steps_taken,
                    complete=True,
                    lockRelease=lock_release,
                )
            )

        if stage == "related-work-checkpoint":
            checkpoint = state.get("pendingRelatedWork")
            if ack_related_work:
                result = acknowledge_related_work(root, state)
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
    try:
        run_id = require_run_id(run_id)
    except RunIdRequiredError as exc:
        fail(str(exc), exit_code=20, halt="doc-run-id-invalid")
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
