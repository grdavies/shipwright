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
LOCKS_DIR_NAME = "sw-deliver-locks"
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


def ship_lease_owner_live(meta: dict[str, Any]) -> bool:
    if ship_steps_in_progress(meta):
        return True
    return not ship_lease_is_stale(meta)


def reclaim_stale_ship_lease(lock_path: Path) -> bool:
    meta = read_lock_meta(lock_path)
    if not meta:
        lock_path.unlink(missing_ok=True)
        return True
    if ship_lease_owner_live(meta):
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
    lock_path = lock_path_for(root, integration, phase_branch)
    if lock_path.is_file():
        existing = read_lock_meta(lock_path)
        if (
            existing.get("pid") == os.getpid()
            and existing.get("threadId") == threading.get_ident()
            and ship_lease_owner_live(existing)
        ):
            return {
                "verdict": "pass",
                "action": "ship-lease-acquire",
                "reentrant": True,
                "integrationBranch": integration,
                "phaseBranch": phase_branch,
                "lockPath": str(lock_path),
            }
    now = utc_now()
    meta: dict[str, Any] = {
        "kind": "ship-lease",
        "integrationBranch": integration,
        "phaseBranch": phase_branch,
        "pid": os.getpid(),
        "threadId": threading.get_ident(),
        "host": lock_host(),
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
        if reclaim_stale_ship_lease(lock_path) and try_acquire():
            append_log(
                root,
                {
                    "event": "ship-lease-reclaim",
                    "integrationBranch": integration,
                    "phaseBranch": phase_branch,
                    "previousHolder": existing,
                },
            )
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
        },
    )
    return {
        "verdict": "pass",
        "action": "ship-lease-acquire",
        "integrationBranch": integration,
        "phaseBranch": phase_branch,
        "lockPath": str(lock_path),
    }


def release_ship_lease(root: Path, args: list[str]) -> dict[str, Any]:
    integration, phase_branch = resolve_branches(root, args)
    lock_path = lock_path_for(root, integration, phase_branch)
    if not lock_path.is_file():
        return {"verdict": "pass", "action": "ship-lease-release", "note": "no lock file"}
    meta = read_lock_meta(lock_path)
    holder_pid = meta.get("pid")
    if isinstance(holder_pid, int) and holder_pid != os.getpid():
        return {"verdict": "fail", "error": "ship-lease-other-pid", "holder": meta}
    lock_path.unlink(missing_ok=True)
    append_log(
        root,
        {
            "event": "ship-lease-release",
            "integrationBranch": integration,
            "phaseBranch": phase_branch,
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
    if out.get("verdict") != "pass":
        fail(out.get("error", "ship lease held"), exit_code=20, holder=out.get("holder"))
    emit(out)


def cmd_release(root: Path, args: list[str]) -> None:
    out = release_ship_lease(root, args)
    if out.get("verdict") != "pass":
        fail(out.get("error", "ship lease release failed"), exit_code=20, holder=out.get("holder"))
    emit(out)


def cmd_heartbeat(root: Path, args: list[str]) -> None:
    integration, phase_branch = resolve_branches(root, args)
    lock_path = lock_path_for(root, integration, phase_branch)
    if not lock_path.is_file():
        fail("ship lease missing", exit_code=20)
    meta = read_lock_meta(lock_path)
    holder_pid = meta.get("pid")
    if isinstance(holder_pid, int) and holder_pid != os.getpid():
        fail("ship lease held by another pid", exit_code=20, holder=meta)
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


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_lock.py <root> <acquire|release|heartbeat|status> ...")
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
    else:
        fail(f"unknown ship-lease subcommand: {sub}")


if __name__ == "__main__":
    main()
