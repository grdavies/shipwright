#!/usr/bin/env python3
"""Per-phase-head single-shipper lease (PRD 036 R2).

Keyed lease files under `.cursor/sw-deliver-locks/<hash>.lock` reuse O_EXCL / reclaim_stale_lock
internals from wave_state. Key is (integrationBranch, phaseBranch). Heartbeat-based liveness with a
short TTL distinct from orchestrator SW_LOCK_STALE_SECONDS.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import threading
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_state import append_log, emit, fail, parse_kv, read_lock_meta, utc_now

SHIP_LEASE_STALE_SECONDS = int(os.environ.get("SW_SHIP_LEASE_STALE_SECONDS", "300"))
RUN_LEASE_STALE_SECONDS = int(os.environ.get("SW_RUN_LEASE_STALE_SECONDS", "300"))
LOCKS_DIR_NAME = "sw-deliver-locks"
TARGET_LOCKS_DIR_NAME = "sw-target-locks"
DOC_RUN_LOCKS_DIR_NAME = "sw-doc-run-locks"
DOC_TO_FEATURE_HANDOFF_LOCKS_DIR_NAME = "sw-doc-to-feature-handoff-locks"
RUN_LEASE_LOCKS_DIR_NAME = "sw-deliver-run-locks"
TARGET_LOCK_JOURNAL_NAME = "reclaim-journal.jsonl"
DOC_RUN_LOCK_JOURNAL_NAME = "reclaim-journal.jsonl"
DOC_TO_FEATURE_HANDOFF_LOCK_JOURNAL_NAME = "reclaim-journal.jsonl"
RUN_LEASE_JOURNAL_NAME = "reclaim-journal.jsonl"
SAFE_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def lock_host() -> str:
    return socket.gethostname()


def _git_toplevel(start: Path) -> Path:
    import subprocess

    out = subprocess.check_output(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        text=True,
    ).strip()
    return Path(out)


def lease_key_hash(integration_branch: str, phase_branch: str) -> str:
    raw = f"{integration_branch}\0{phase_branch}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def sanitize_lock_component(value: str) -> str:
    cleaned = SAFE_SLUG_RE.sub("_", value.strip())
    return cleaned[:120] or "unknown"


def locks_dir(root: Path) -> Path:
    top = _git_toplevel(root)
    base = (top / ".cursor" / LOCKS_DIR_NAME).resolve()
    parent = base.parent.resolve()
    if parent.is_symlink():
        fail("lock parent is symlinked", exit_code=20, halt="lock-path-unsafe")
    base.mkdir(parents=True, exist_ok=True)
    return base


def lock_path_for(root: Path, integration_branch: str, phase_branch: str) -> Path:
    locks = locks_dir(root)
    digest = lease_key_hash(integration_branch, phase_branch)
    safe_phase = sanitize_lock_component(phase_branch.rsplit("/", 1)[-1])
    filename = f"{digest}-{safe_phase}.lock"
    path = (locks / filename).resolve()
    if path.parent != locks:
        fail("lock path escapes locks directory", exit_code=20, halt="lock-path-unsafe")
    if path.parent.is_symlink():
        fail("locks directory is symlinked", exit_code=20, halt="lock-path-unsafe")
    return path


def _canonical_repo_root_for_locks(start: Path) -> Path:
    from wave_state import canonical_repo_root

    return canonical_repo_root(start)


def target_locks_dir(root: Path) -> Path:
    """Git-common-dir anchored target-lock directory outside run directories (R19)."""
    repo_root = _canonical_repo_root_for_locks(root)
    base_raw = repo_root / ".cursor" / TARGET_LOCKS_DIR_NAME
    parent_raw = repo_root / ".cursor"
    if parent_raw.is_symlink():
        fail("target-lock parent is symlinked", exit_code=20, halt="lock-path-unsafe")
    if base_raw.is_symlink():
        fail("target-lock directory is symlinked", exit_code=20, halt="lock-path-unsafe")
    base = base_raw.resolve()
    parent = base.parent.resolve()
    if parent.is_symlink():
        fail("target-lock parent is symlinked", exit_code=20, halt="lock-path-unsafe")
    base.mkdir(parents=True, exist_ok=True)
    return base


def target_lock_path_for(root: Path, target_branch: str) -> Path:
    locks = target_locks_dir(root)
    digest = target_lock_key_digest(root, target_branch)
    safe_target = sanitize_lock_component(target_branch.rsplit("/", 1)[-1])
    filename = f"{digest}-{safe_target}.lock"
    path = (locks / filename).resolve()
    if path.parent != locks:
        fail("target lock path escapes locks directory", exit_code=20, halt="lock-path-unsafe")
    locks_raw = _canonical_repo_root_for_locks(root) / ".cursor" / TARGET_LOCKS_DIR_NAME
    if locks_raw.is_symlink():
        fail("target locks directory is symlinked", exit_code=20, halt="lock-path-unsafe")
    return path


def repository_identity(root: Path) -> str:
    repo = _canonical_repo_root_for_locks(root)
    return hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()[:32]


def target_lock_key_digest(root: Path, target_branch: str) -> str:
    raw = f"{repository_identity(root)}\0{target_branch}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def doc_run_locks_dir(root: Path) -> Path:
    """Git-common-dir anchored doc-run lock directory outside run directories (R11)."""
    repo_root = _canonical_repo_root_for_locks(root)
    base_raw = repo_root / ".cursor" / DOC_RUN_LOCKS_DIR_NAME
    parent_raw = repo_root / ".cursor"
    if parent_raw.is_symlink():
        fail("doc-run-lock parent is symlinked", exit_code=20, halt="lock-path-unsafe")
    if base_raw.is_symlink():
        fail("doc-run-lock directory is symlinked", exit_code=20, halt="lock-path-unsafe")
    base = base_raw.resolve()
    parent = base.parent.resolve()
    if parent.is_symlink():
        fail("doc-run-lock parent is symlinked", exit_code=20, halt="lock-path-unsafe")
    base.mkdir(parents=True, exist_ok=True)
    return base


def doc_run_lock_path_for(root: Path, topic: str) -> Path:
    locks = doc_run_locks_dir(root)
    digest = doc_run_lock_key_digest(root, topic)
    safe_topic = sanitize_lock_component(topic)
    filename = f"{digest}-{safe_topic}.lock"
    path = (locks / filename).resolve()
    if path.parent != locks:
        fail("doc-run lock path escapes locks directory", exit_code=20, halt="lock-path-unsafe")
    locks_raw = _canonical_repo_root_for_locks(root) / ".cursor" / DOC_RUN_LOCKS_DIR_NAME
    if locks_raw.is_symlink():
        fail("doc-run locks directory is symlinked", exit_code=20, halt="lock-path-unsafe")
    return path


def doc_run_lock_key_digest(root: Path, topic: str) -> str:
    raw = f"{repository_identity(root)}\0doc-topic\0{topic}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def doc_to_feature_handoff_locks_dir(root: Path) -> Path:
    """Git-common-dir anchored doc-to-feature handoff lock directory (PRD 085 R14)."""
    repo_root = _canonical_repo_root_for_locks(root)
    base_raw = repo_root / ".cursor" / DOC_TO_FEATURE_HANDOFF_LOCKS_DIR_NAME
    parent_raw = repo_root / ".cursor"
    if parent_raw.is_symlink():
        fail("doc-to-feature-handoff-lock parent is symlinked", exit_code=20, halt="lock-path-unsafe")
    if base_raw.is_symlink():
        fail("doc-to-feature-handoff-lock directory is symlinked", exit_code=20, halt="lock-path-unsafe")
    base = base_raw.resolve()
    parent = base.parent.resolve()
    if parent.is_symlink():
        fail("doc-to-feature-handoff-lock parent is symlinked", exit_code=20, halt="lock-path-unsafe")
    base.mkdir(parents=True, exist_ok=True)
    return base


def doc_to_feature_handoff_lock_key_digest(root: Path, target_branch: str, run_id: str) -> str:
    raw = f"{repository_identity(root)}\0doc-to-feature-handoff\0{target_branch}\0{run_id}".encode(
        "utf-8"
    )
    return hashlib.sha256(raw).hexdigest()[:32]


def doc_to_feature_handoff_lock_path_for(root: Path, target_branch: str, run_id: str) -> Path:
    locks = doc_to_feature_handoff_locks_dir(root)
    digest = doc_to_feature_handoff_lock_key_digest(root, target_branch, run_id)
    safe_target = sanitize_lock_component(target_branch.rsplit("/", 1)[-1])
    safe_run = sanitize_lock_component(run_id.replace(":", "-"))
    filename = f"{digest}-{safe_target}-{safe_run}.lock"
    path = (locks / filename).resolve()
    if path.parent != locks:
        fail("doc-to-feature-handoff lock path escapes locks directory", exit_code=20, halt="lock-path-unsafe")
    locks_raw = _canonical_repo_root_for_locks(root) / ".cursor" / DOC_TO_FEATURE_HANDOFF_LOCKS_DIR_NAME
    if locks_raw.is_symlink():
        fail("doc-to-feature-handoff locks directory is symlinked", exit_code=20, halt="lock-path-unsafe")
    return path


def doc_to_feature_handoff_lock_journal_path(root: Path) -> Path:
    return doc_to_feature_handoff_locks_dir(root) / DOC_TO_FEATURE_HANDOFF_LOCK_JOURNAL_NAME


def append_doc_to_feature_handoff_lock_journal(root: Path, entry: dict[str, Any]) -> None:
    """Append reclaim journal entry; write failure fails takeover closed (R14)."""
    journal = doc_to_feature_handoff_lock_journal_path(root)
    line = json.dumps({**entry, "at": utc_now()}, ensure_ascii=False) + "\n"
    try:
        with open(journal, "a", encoding="utf-8") as handle:
            handle.write(line)
        os.chmod(journal, 0o600)
    except OSError as exc:
        fail(
            "doc-to-feature-handoff-lock journal write failed",
            exit_code=20,
            halt="doc-to-feature-handoff-lock-journal-write-failed",
            error=str(exc),
        )


def doc_run_lock_journal_path(root: Path) -> Path:
    return doc_run_locks_dir(root) / DOC_RUN_LOCK_JOURNAL_NAME


def append_doc_run_lock_journal(root: Path, entry: dict[str, Any]) -> None:
    """Append reclaim journal entry; write failure fails takeover closed (R11)."""
    journal = doc_run_lock_journal_path(root)
    line = json.dumps({**entry, "at": utc_now()}, ensure_ascii=False) + "\n"
    try:
        with open(journal, "a", encoding="utf-8") as handle:
            handle.write(line)
        os.chmod(journal, 0o600)
    except OSError as exc:
        fail(
            "doc-run-lock journal write failed",
            exit_code=20,
            halt="doc-run-lock-journal-write-failed",
            error=str(exc),
        )


def target_lock_journal_path(root: Path) -> Path:
    return target_locks_dir(root) / TARGET_LOCK_JOURNAL_NAME


def append_target_lock_journal(root: Path, entry: dict[str, Any]) -> None:
    """Append reclaim journal entry; write failure fails takeover closed (R19)."""
    journal = target_lock_journal_path(root)
    line = json.dumps({**entry, "at": utc_now()}, ensure_ascii=False) + "\n"
    try:
        with open(journal, "a", encoding="utf-8") as handle:
            handle.write(line)
        os.chmod(journal, 0o600)
    except OSError as exc:
        fail(
            "target-lock journal write failed",
            exit_code=20,
            halt="target-lock-journal-write-failed",
            error=str(exc),
        )


def ship_steps_in_progress(meta: dict[str, Any]) -> bool:
    steps = meta.get("shipSteps")
    if not isinstance(steps, dict):
        return False
    current = steps.get("currentStep")
    if not current:
        return False
    terminal = {"sw-ready", "sw-tmp-clean", "complete"}
    return str(current) not in terminal


def ship_lease_is_stale(meta: dict[str, Any]) -> bool:
    hb = meta.get("heartbeatAt") or meta.get("acquiredAt")
    if not isinstance(hb, str):
        return True
    try:
        dt = datetime.strptime(hb, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age > SHIP_LEASE_STALE_SECONDS
    except ValueError:
        return True


def ship_lease_pid_alive(meta: dict[str, Any]) -> bool:
    """True when lease PID is still alive on this host."""
    pid = meta.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError, PermissionError):
        return False


def ship_lease_owner_live(meta: dict[str, Any]) -> bool:
    """Lease is live when heartbeat is fresh OR (same-host and PID still alive).

    Reclaim requires stale heartbeat AND dead PID on the same host (PRD 067 R7).
    """
    if not ship_lease_is_stale(meta):
        return True
    if meta.get("host") == lock_host() and ship_lease_pid_alive(meta):
        return True
    return False


def resolve_node_id(args: list[str]) -> str:
    """Per-node owner token identity for concurrent graph dispatch (PRD 269 R5)."""
    raw = parse_kv(args, "--node-id") or os.environ.get("SW_NODE_ID", "").strip()
    return str(raw).strip() if raw else ""


def owner_token_from_meta(meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "pid": meta.get("pid"),
        "threadId": meta.get("threadId"),
        "nodeId": str(meta.get("nodeId") or ""),
    }


def current_owner_token(node_id: str) -> dict[str, Any]:
    return {
        "pid": os.getpid(),
        "threadId": threading.get_ident(),
        "nodeId": str(node_id or ""),
    }


def owner_token_matches(meta: dict[str, Any], node_id: str) -> bool:
    """True when lease holder matches pid + thread + nodeId (R5)."""
    held = owner_token_from_meta(meta)
    want = current_owner_token(node_id)
    return (
        held.get("pid") == want["pid"]
        and held.get("threadId") == want["threadId"]
        and held.get("nodeId") == want["nodeId"]
    )


def phase_status_consumable_terminal(root: Path, phase_slug: str | None) -> bool:
    if not phase_slug:
        return False
    status_path = root / ".cursor" / "sw-deliver-runs" / phase_slug / "status.json"
    if not status_path.is_file():
        return False
    try:
        from status_integrity import status_is_consumable_terminal

        payload = json.loads(status_path.read_text(encoding="utf-8"))
        return status_is_consumable_terminal(payload)
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return False


def reclaim_stale_ship_lease(
    lock_path: Path,
    *,
    root: Path | None = None,
    phase_slug: str | None = None,
    start_token: str | None = None,
) -> bool:
    """Reclaim only for same-host leases with stale heartbeat AND dead PID (PRD 067 R7)."""
    meta = read_lock_meta(lock_path)
    if not meta:
        lock_path.unlink(missing_ok=True)
        return True
    if meta.get("host") and meta.get("host") != lock_host():
        return False
    if start_token and meta.get("startToken") and meta.get("startToken") != start_token:
        return False
    if ship_lease_owner_live(meta):
        return False
    if root is not None and phase_status_consumable_terminal(root, phase_slug):
        return False
    if not ship_lease_is_stale(meta):
        return False
    if ship_lease_pid_alive(meta):
        return False
    lock_path.unlink(missing_ok=True)
    return True


def resolve_branches(root: Path, args: list[str]) -> tuple[str, str]:
    integration = parse_kv(args, "--integration")
    phase_branch = parse_kv(args, "--phase-branch")
    if integration and phase_branch:
        return integration, phase_branch
    from wave_phase_pr import integration_branch

    integ = integration or integration_branch(root)
    phase = phase_branch or os.environ.get("SW_PHASE_BRANCH", "").strip()
    if not integ:
        fail("--integration or deliver state integration branch required")
    if not phase:
        fail("--phase-branch or SW_PHASE_BRANCH required")
    return integ, phase


def acquire_ship_lease(root: Path, args: list[str]) -> dict[str, Any]:
    integration, phase_branch = resolve_branches(root, args)
    phase_slug = parse_kv(args, "--phase-slug")
    node_id = resolve_node_id(args)
    lock_path = lock_path_for(root, integration, phase_branch)
    if lock_path.is_file():
        existing = read_lock_meta(lock_path)
        if owner_token_matches(existing, node_id) and ship_lease_owner_live(existing):
            return {
                "verdict": "pass",
                "action": "ship-lease-acquire",
                "reentrant": True,
                "integrationBranch": integration,
                "phaseBranch": phase_branch,
                "lockPath": str(lock_path),
                "ownerToken": owner_token_from_meta(existing),
            }
    now = utc_now()
    start_token = parse_kv(args, "--start-token") or os.environ.get("SW_SHIP_START_TOKEN") or ""
    owner = current_owner_token(node_id)
    meta: dict[str, Any] = {
        "kind": "ship-lease",
        "integrationBranch": integration,
        "phaseBranch": phase_branch,
        "pid": owner["pid"],
        "threadId": owner["threadId"],
        "nodeId": owner["nodeId"],
        "host": lock_host(),
        "startToken": start_token or f"{os.getpid()}-{now}",
        "acquiredAt": now,
        "heartbeatAt": now,
    }
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY

    def try_acquire() -> bool:
        try:
            fd = os.open(lock_path, flags, 0o600)
        except FileExistsError:
            return False
        os.write(fd, (json.dumps(meta) + "\n").encode("utf-8"))
        os.close(fd)
        return True

    if not try_acquire():
        existing = read_lock_meta(lock_path)
        if (
            reclaim_stale_ship_lease(
                lock_path, root=root, phase_slug=phase_slug, start_token=start_token or None
            )
            and try_acquire()
        ):
            append_log(
                root,
                {
                    "event": "ship-lease-reclaim",
                    "integrationBranch": integration,
                    "phaseBranch": phase_branch,
                    "previousHolder": existing,
                },
            )
        elif ship_lease_owner_live(existing) and not owner_token_matches(existing, node_id):
            # R5: concurrent foreign owner parks instead of failing the run.
            return {
                "verdict": "park",
                "action": "ship-lease-acquire",
                "error": "ship-lease-parked",
                "holder": existing,
                "ownerToken": owner,
                "lockPath": str(lock_path),
            }
        else:
            return {
                "verdict": "fail",
                "error": "ship-lease-held",
                "holder": existing,
                "lockPath": str(lock_path),
            }
    append_log(
        root,
        {
            "event": "ship-lease-acquire",
            "integrationBranch": integration,
            "phaseBranch": phase_branch,
            "nodeId": node_id,
        },
    )
    return {
        "verdict": "pass",
        "action": "ship-lease-acquire",
        "integrationBranch": integration,
        "phaseBranch": phase_branch,
        "lockPath": str(lock_path),
        "ownerToken": owner,
    }


def release_ship_lease(root: Path, args: list[str], *, finalize: bool = False) -> dict[str, Any]:
    integration, phase_branch = resolve_branches(root, args)
    node_id = resolve_node_id(args)
    lock_path = lock_path_for(root, integration, phase_branch)
    if not lock_path.is_file():
        return {"verdict": "pass", "action": "ship-lease-release", "note": "no lock file"}
    meta = read_lock_meta(lock_path)
    # R5: finalize does not skip ownership — foreign owner never releases.
    if not owner_token_matches(meta, node_id):
        return {
            "verdict": "fail",
            "error": "ship-lease-owner-mismatch",
            "holder": meta,
            "finalize": bool(finalize),
            "ownerToken": current_owner_token(node_id),
        }
    lock_path.unlink(missing_ok=True)
    append_log(
        root,
        {
            "event": "ship-lease-release",
            "integrationBranch": integration,
            "phaseBranch": phase_branch,
            "nodeId": node_id,
            "finalize": bool(finalize),
        },
    )
    return {
        "verdict": "pass",
        "action": "ship-lease-release",
        "integrationBranch": integration,
        "phaseBranch": phase_branch,
    }


def cmd_acquire(root: Path, args: list[str]) -> None:
    out = acquire_ship_lease(root, args)
    if out.get("verdict") == "park":
        emit(out)
        return
    if out.get("verdict") != "pass":
        fail(out.get("error", "ship lease held"), exit_code=20, holder=out.get("holder"))
    emit(out)


def cmd_release(root: Path, args: list[str]) -> None:
    finalize = "--finalize" in args
    out = release_ship_lease(root, args, finalize=finalize)
    if out.get("verdict") != "pass":
        fail(out.get("error", "ship lease release failed"), exit_code=20, holder=out.get("holder"))
    emit(out)


def cmd_heartbeat(root: Path, args: list[str]) -> None:
    integration, phase_branch = resolve_branches(root, args)
    node_id = resolve_node_id(args)
    lock_path = lock_path_for(root, integration, phase_branch)
    if not lock_path.is_file():
        fail("ship lease missing", exit_code=20)
    meta = read_lock_meta(lock_path)
    if not owner_token_matches(meta, node_id):
        fail("ship lease held by another owner", exit_code=20, holder=meta)
    ship_steps_raw = parse_kv(args, "--ship-steps")
    if ship_steps_raw:
        try:
            meta["shipSteps"] = json.loads(ship_steps_raw)
        except json.JSONDecodeError:
            fail("invalid --ship-steps json")
    now = utc_now()
    meta["heartbeatAt"] = now
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
    os.chmod(lock_path, 0o600)
    emit(
        {
            "verdict": "pass",
            "action": "ship-lease-heartbeat",
            "heartbeatAt": now,
        }
    )


def cmd_status(root: Path, args: list[str]) -> None:
    integration, phase_branch = resolve_branches(root, args)
    lock_path = lock_path_for(root, integration, phase_branch)
    if not lock_path.is_file():
        emit(
            {
                "verdict": "pass",
                "action": "ship-lease-status",
                "held": False,
                "lockPath": str(lock_path),
            }
        )
    meta = read_lock_meta(lock_path)
    emit(
        {
            "verdict": "pass",
            "action": "ship-lease-status",
            "held": True,
            "live": ship_lease_owner_live(meta),
            "meta": meta,
            "lockPath": str(lock_path),
        }
    )


# --- Exclusive deliver runId lease (PRD 276 R9–R12, R20, R21) -----------------


def run_lease_locks_dir(root: Path) -> Path:
    """Git-common-dir anchored exclusive run-lease directory (R21)."""
    repo_root = _canonical_repo_root_for_locks(root)
    base_raw = repo_root / ".cursor" / RUN_LEASE_LOCKS_DIR_NAME
    parent_raw = repo_root / ".cursor"
    if parent_raw.is_symlink():
        fail("run-lease parent is symlinked", exit_code=20, halt="lock-path-unsafe")
    if base_raw.is_symlink():
        fail("run-lease directory is symlinked", exit_code=20, halt="lock-path-unsafe")
    base = base_raw.resolve()
    parent = base.parent.resolve()
    if parent.is_symlink():
        fail("run-lease parent is symlinked", exit_code=20, halt="lock-path-unsafe")
    base.mkdir(parents=True, exist_ok=True)
    return base


def run_lease_key_digest(root: Path, run_id: str) -> str:
    raw = f"{repository_identity(root)}\0deliver-run-lease\0{run_id}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def run_lease_path_for(root: Path, run_id: str) -> Path:
    locks = run_lease_locks_dir(root)
    digest = run_lease_key_digest(root, run_id)
    safe_run = sanitize_lock_component(run_id.replace(":", "-"))
    filename = f"{digest}-{safe_run}.lock"
    path = (locks / filename).resolve()
    if path.parent != locks:
        fail("run-lease path escapes locks directory", exit_code=20, halt="lock-path-unsafe")
    locks_raw = _canonical_repo_root_for_locks(root) / ".cursor" / RUN_LEASE_LOCKS_DIR_NAME
    if locks_raw.is_symlink():
        fail("run-lease locks directory is symlinked", exit_code=20, halt="lock-path-unsafe")
    return path


def run_lease_journal_path(root: Path) -> Path:
    return run_lease_locks_dir(root) / RUN_LEASE_JOURNAL_NAME


def append_run_lease_journal(root: Path, entry: dict[str, Any]) -> None:
    """Append reclaim journal entry; write failure fails takeover closed."""
    journal = run_lease_journal_path(root)
    line = json.dumps({**entry, "at": utc_now()}, ensure_ascii=False) + "\n"
    try:
        with open(journal, "a", encoding="utf-8") as handle:
            handle.write(line)
        os.chmod(journal, 0o600)
    except OSError as exc:
        fail(
            "run-lease journal write failed",
            exit_code=20,
            halt="run-lease-journal-write-failed",
            error=str(exc),
        )


def run_lease_is_stale(meta: dict[str, Any]) -> bool:
    hb = meta.get("heartbeatAt") or meta.get("acquiredAt")
    if not isinstance(hb, str):
        return True
    try:
        dt = datetime.strptime(hb, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age > RUN_LEASE_STALE_SECONDS
    except ValueError:
        return True


def run_lease_owner_live(meta: dict[str, Any]) -> bool:
    """Live when heartbeat fresh OR (same-host and PID still alive)."""
    if not run_lease_is_stale(meta):
        return True
    if meta.get("host") == lock_host() and ship_lease_pid_alive(meta):
        return True
    return False


def run_lease_ownership_certain(meta: dict[str, Any]) -> bool:
    """False when host/pid identity is missing or unusable (R21 fail-closed)."""
    host = meta.get("host")
    pid = meta.get("pid")
    if not isinstance(host, str) or not host.strip():
        return False
    if not isinstance(pid, int) or pid <= 0:
        return False
    return True


def _run_lease_generation(meta: dict[str, Any]) -> int:
    raw = meta.get("generation")
    try:
        gen = int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        return 0
    return gen if gen > 0 else 0


def _run_lease_resume_command(run_id: str, source_task_list: str | None = None) -> str:
    if source_task_list:
        return f"python3 scripts/wave.py deliver-loop --task-list {source_task_list}"
    return f"python3 scripts/wave.py deliver-loop --run-id {run_id}"


def reclaim_stale_run_lease(
    lock_path: Path,
    *,
    root: Path,
    reclaiming_run_id: str,
    takeover_reason: str,
    cross_host_ack: bool = False,
) -> tuple[bool, int]:
    """Reclaim stale run lease; bump generation on success (R11/R20).

    Returns (reclaimed, next_generation). Uncertain ownership fails closed (R21).
    """
    meta = read_lock_meta(lock_path)
    if not meta:
        lock_path.unlink(missing_ok=True)
        return True, 1
    if not run_lease_ownership_certain(meta):
        return False, _run_lease_generation(meta)
    holder_host = meta.get("host")
    if holder_host and holder_host != lock_host():
        # R21 — no automatic cross-clone/cross-host reclaim without explicit ack.
        if not cross_host_ack:
            return False, _run_lease_generation(meta)
        if not run_lease_is_stale(meta):
            return False, _run_lease_generation(meta)
    else:
        if run_lease_owner_live(meta):
            return False, _run_lease_generation(meta)
        if not run_lease_is_stale(meta):
            return False, _run_lease_generation(meta)
        if ship_lease_pid_alive(meta):
            return False, _run_lease_generation(meta)
    prior_gen = _run_lease_generation(meta)
    next_gen = max(prior_gen, 0) + 1
    journal_entry = {
        "kind": "deliver-run-lease-reclaim",
        "reclaimedOwner": meta.get("owner"),
        "reclaimedHost": meta.get("host"),
        "reclaimedPid": meta.get("pid"),
        "reclaimedAcquiredAt": meta.get("acquiredAt"),
        "reclaimedHeartbeatAt": meta.get("heartbeatAt"),
        "reclaimedRunId": meta.get("runId"),
        "reclaimedGeneration": prior_gen,
        "nextGeneration": next_gen,
        "takeoverReason": takeover_reason,
        "reclaimingRunId": reclaiming_run_id,
    }
    append_run_lease_journal(root, journal_entry)
    lock_path.unlink(missing_ok=True)
    return True, next_gen


def _run_lease_meta(
    *,
    run_id: str,
    generation: int,
    host: str | None = None,
    pid: int | None = None,
) -> dict[str, Any]:
    now = utc_now()
    host_val = host or lock_host()
    pid_val = pid if pid is not None else os.getpid()
    return {
        "kind": "deliver-run-lease",
        "runId": run_id,
        "generation": int(generation),
        "owner": f"{host_val}:{pid_val}",
        "host": host_val,
        "pid": pid_val,
        "acquiredAt": now,
        "heartbeatAt": now,
    }


def acquire_run_lease(
    root: Path,
    run_id: str,
    *,
    cross_host_ack: bool = False,
    source_task_list: str | None = None,
) -> dict[str, Any]:
    """Acquire exclusive deliver runId lease before mutating run state (R9/R10)."""
    try:
        import state_root_migrate as srm

        srm.assert_no_quiesce_fence(root)
    except Exception as exc:  # noqa: BLE001 - map fence refusal into lease fail payload
        if exc.__class__.__name__ == "StateRootMigrateError":
            return {
                "verdict": "fail",
                "error": getattr(exc, "code", "quiesce-fence-blocks-acquire"),
                "halt": getattr(exc, "code", "quiesce-fence-blocks-acquire"),
                "message": getattr(exc, "message", str(exc)),
                **getattr(exc, "extra", {}),
            }
        raise
    if not isinstance(run_id, str) or not run_id.strip():
        return {
            "verdict": "fail",
            "error": "run-lease-missing-run-id",
            "halt": "run-lease-missing-run-id",
            "resumeCommand": _run_lease_resume_command(run_id or "unknown", source_task_list),
        }
    run_id = run_id.strip()
    lock_path = run_lease_path_for(root, run_id)
    digest = run_lease_key_digest(root, run_id)
    if lock_path.is_file():
        existing = read_lock_meta(lock_path)
        if (
            existing.get("runId") == run_id
            and existing.get("pid") == os.getpid()
            and existing.get("host") == lock_host()
            and run_lease_owner_live(existing)
        ):
            gen = _run_lease_generation(existing) or 1
            return {
                "verdict": "pass",
                "action": "run-lease-acquire",
                "reentrant": True,
                "runId": run_id,
                "generation": gen,
                "lockPath": str(lock_path),
                "lockKeyDigest": digest,
            }
    generation = 1
    meta = _run_lease_meta(run_id=run_id, generation=generation)
    meta["lockKeyDigest"] = digest
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY

    def try_acquire(gen: int) -> bool:
        payload = _run_lease_meta(run_id=run_id, generation=gen)
        payload["lockKeyDigest"] = digest
        try:
            fd = os.open(lock_path, flags, 0o600)
        except FileExistsError:
            return False
        os.write(fd, (json.dumps(payload) + "\n").encode("utf-8"))
        os.close(fd)
        return True

    if try_acquire(generation):
        append_log(
            root,
            {
                "event": "run-lease-acquire",
                "runId": run_id,
                "generation": generation,
            },
        )
        return {
            "verdict": "pass",
            "action": "run-lease-acquire",
            "runId": run_id,
            "generation": generation,
            "lockPath": str(lock_path),
            "lockKeyDigest": digest,
        }

    existing = read_lock_meta(lock_path)
    reason = "cross-host-ack" if cross_host_ack else "stale-heartbeat-dead-pid"
    reclaimed, next_gen = reclaim_stale_run_lease(
        lock_path,
        root=root,
        reclaiming_run_id=run_id,
        takeover_reason=reason,
        cross_host_ack=cross_host_ack,
    )
    if reclaimed and try_acquire(next_gen):
        append_log(
            root,
            {
                "event": "run-lease-reclaim",
                "runId": run_id,
                "generation": next_gen,
                "previousHolder": existing,
            },
        )
        return {
            "verdict": "pass",
            "action": "run-lease-acquire",
            "reclaimed": True,
            "runId": run_id,
            "generation": next_gen,
            "lockPath": str(lock_path),
            "lockKeyDigest": digest,
            "previousHolder": existing,
        }

    # Live foreign holder or uncertain ownership — typed halt (R10/R21).
    error = "run-lease-held"
    halt = "run-lease-held"
    if existing and not run_lease_ownership_certain(existing):
        error = "run-lease-ownership-uncertain"
        halt = "run-lease-ownership-uncertain"
    elif existing and existing.get("host") and existing.get("host") != lock_host():
        error = "run-lease-cross-host"
        halt = "run-lease-cross-host"
    return {
        "verdict": "fail",
        "error": error,
        "halt": halt,
        "holder": existing,
        "lockPath": str(lock_path),
        "resumeCommand": _run_lease_resume_command(run_id, source_task_list),
    }


def heartbeat_run_lease(root: Path, run_id: str, generation: int) -> dict[str, Any]:
    """Heartbeat with generation fencing — stale generation fails closed (R20)."""
    lock_path = run_lease_path_for(root, run_id)
    if not lock_path.is_file():
        return {"verdict": "fail", "error": "run-lease-missing", "lockPath": str(lock_path)}
    meta = read_lock_meta(lock_path)
    if meta.get("runId") != run_id:
        return {"verdict": "fail", "error": "run-lease-run-mismatch", "holder": meta}
    current_gen = _run_lease_generation(meta)
    if int(generation) != current_gen:
        return {
            "verdict": "fail",
            "error": "run-lease-generation-stale",
            "halt": "run-lease-generation-stale",
            "holder": meta,
            "expectedGeneration": current_gen,
            "providedGeneration": int(generation),
        }
    if meta.get("pid") != os.getpid():
        return {"verdict": "fail", "error": "run-lease-other-pid", "holder": meta}
    if meta.get("host") != lock_host():
        return {"verdict": "fail", "error": "run-lease-other-host", "holder": meta}
    now = utc_now()
    meta["heartbeatAt"] = now
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
    os.chmod(lock_path, 0o600)
    return {
        "verdict": "pass",
        "action": "run-lease-heartbeat",
        "heartbeatAt": now,
        "runId": run_id,
        "generation": current_gen,
    }


def assert_run_lease_write(
    root: Path,
    run_id: str,
    generation: int,
) -> dict[str, Any]:
    """Fence a shared-state write: generation must match live lock (R20)."""
    lock_path = run_lease_path_for(root, run_id)
    if not lock_path.is_file():
        return {
            "verdict": "fail",
            "error": "run-lease-missing",
            "halt": "run-lease-missing",
            "lockPath": str(lock_path),
            "resumeCommand": _run_lease_resume_command(run_id),
        }
    meta = read_lock_meta(lock_path)
    if not run_lease_ownership_certain(meta):
        return {
            "verdict": "fail",
            "error": "run-lease-ownership-uncertain",
            "halt": "run-lease-ownership-uncertain",
            "holder": meta,
            "resumeCommand": _run_lease_resume_command(run_id),
        }
    if meta.get("runId") != run_id:
        return {
            "verdict": "fail",
            "error": "run-lease-run-mismatch",
            "halt": "run-lease-run-mismatch",
            "holder": meta,
            "resumeCommand": _run_lease_resume_command(run_id),
        }
    current_gen = _run_lease_generation(meta)
    if int(generation) != current_gen:
        return {
            "verdict": "fail",
            "error": "run-lease-generation-stale",
            "halt": "run-lease-generation-stale",
            "holder": meta,
            "expectedGeneration": current_gen,
            "providedGeneration": int(generation),
            "resumeCommand": _run_lease_resume_command(run_id),
        }
    if meta.get("host") != lock_host() or meta.get("pid") != os.getpid():
        return {
            "verdict": "fail",
            "error": "run-lease-held",
            "halt": "run-lease-held",
            "holder": meta,
            "resumeCommand": _run_lease_resume_command(run_id),
        }
    if not run_lease_owner_live(meta):
        return {
            "verdict": "fail",
            "error": "run-lease-stale-self",
            "halt": "run-lease-stale-self",
            "holder": meta,
            "resumeCommand": _run_lease_resume_command(run_id),
        }
    return {
        "verdict": "pass",
        "action": "run-lease-assert-write",
        "runId": run_id,
        "generation": current_gen,
        "lockPath": str(lock_path),
    }


def release_run_lease(root: Path, run_id: str, generation: int | None = None) -> dict[str, Any]:
    lock_path = run_lease_path_for(root, run_id)
    if not lock_path.is_file():
        return {"verdict": "pass", "action": "run-lease-release", "note": "no lock file"}
    meta = read_lock_meta(lock_path)
    if meta.get("runId") != run_id:
        return {"verdict": "fail", "error": "run-lease-run-mismatch", "holder": meta}
    if meta.get("pid") != os.getpid() or meta.get("host") != lock_host():
        return {"verdict": "fail", "error": "run-lease-owner-mismatch", "holder": meta}
    if generation is not None and int(generation) != _run_lease_generation(meta):
        return {
            "verdict": "fail",
            "error": "run-lease-generation-stale",
            "holder": meta,
            "expectedGeneration": _run_lease_generation(meta),
            "providedGeneration": int(generation),
        }
    lock_path.unlink(missing_ok=True)
    append_log(root, {"event": "run-lease-release", "runId": run_id})
    return {"verdict": "pass", "action": "run-lease-release", "runId": run_id}


def status_run_lease(root: Path, run_id: str) -> dict[str, Any]:
    lock_path = run_lease_path_for(root, run_id)
    if not lock_path.is_file():
        return {
            "verdict": "pass",
            "action": "run-lease-status",
            "held": False,
            "lockPath": str(lock_path),
        }
    meta = read_lock_meta(lock_path)
    return {
        "verdict": "pass",
        "action": "run-lease-status",
        "held": True,
        "live": run_lease_owner_live(meta),
        "meta": meta,
        "generation": _run_lease_generation(meta),
        "lockPath": str(lock_path),
    }


def cmd_run_lease(root: Path, args: list[str]) -> None:
    if not args:
        fail(
            "usage: wave_lock.py <root> run-lease "
            "<acquire|release|heartbeat|status|assert-write> --run-id <id> ..."
        )
    action = args[0]
    rest = args[1:]
    run_id = parse_kv(rest, "--run-id") or os.environ.get("SW_DELIVER_RUN_ID", "")
    source_task_list = parse_kv(rest, "--task-list")
    cross_host_ack = "--cross-host-ack" in rest
    gen_raw = parse_kv(rest, "--generation")
    generation = int(gen_raw) if gen_raw is not None else None

    if action == "acquire":
        out = acquire_run_lease(
            root,
            str(run_id or ""),
            cross_host_ack=cross_host_ack,
            source_task_list=source_task_list,
        )
        if out.get("verdict") != "pass":
            fail(
                str(out.get("error") or "run-lease-held"),
                exit_code=20,
                halt=out.get("halt") or out.get("error"),
                holder=out.get("holder"),
                resumeCommand=out.get("resumeCommand"),
                lockPath=out.get("lockPath"),
            )
        emit(out)
        return
    if action == "release":
        out = release_run_lease(root, str(run_id or ""), generation)
        if out.get("verdict") != "pass":
            fail(str(out.get("error") or "run-lease-release-failed"), exit_code=20, holder=out.get("holder"))
        emit(out)
        return
    if action == "heartbeat":
        if generation is None:
            fail("--generation required for run-lease heartbeat")
        out = heartbeat_run_lease(root, str(run_id or ""), generation)
        if out.get("verdict") != "pass":
            fail(
                str(out.get("error") or "run-lease-heartbeat-failed"),
                exit_code=20,
                halt=out.get("halt") or out.get("error"),
                holder=out.get("holder"),
            )
        emit(out)
        return
    if action == "status":
        emit(status_run_lease(root, str(run_id or "")))
        return
    if action == "assert-write":
        if generation is None:
            fail("--generation required for run-lease assert-write")
        out = assert_run_lease_write(root, str(run_id or ""), generation)
        if out.get("verdict") != "pass":
            fail(
                str(out.get("error") or "run-lease-assert-write-failed"),
                exit_code=20,
                halt=out.get("halt") or out.get("error"),
                holder=out.get("holder"),
                resumeCommand=out.get("resumeCommand"),
            )
        emit(out)
        return
    fail(f"unknown run-lease subcommand: {action}")


def main() -> None:
    if len(sys.argv) < 3:
        fail(
            "usage: wave_lock.py <root> <acquire|release|heartbeat|status|run-lease> ..."
        )
    root = Path(sys.argv[1]).resolve()
    sub = sys.argv[2]
    rest = sys.argv[3:]
    if sub == "acquire":
        cmd_acquire(root, rest)
    elif sub == "release":
        cmd_release(root, rest)
    elif sub == "heartbeat":
        cmd_heartbeat(root, rest)
    elif sub == "status":
        cmd_status(root, rest)
    elif sub == "run-lease":
        cmd_run_lease(root, rest)
    else:
        fail(f"unknown ship-lease subcommand: {sub}")


if __name__ == "__main__":
    main()
