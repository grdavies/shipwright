#!/usr/bin/env python3
"""Durable step-level state for /sw-ship phase-mode resume (R58)."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kernel_classification import canonical_ship_chain, normalize_step
from wave_json_io import StateCorruptError, read_json, write_json


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


# Single-sourced from core/sw-reference/kernel-classification.json (PRD 022 TR1).
SHIP_CHAIN: list[str] = canonical_ship_chain(_repo_root())


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)




def chain_index(step: str) -> int:
    norm = normalize_step(step)
    if norm not in SHIP_CHAIN:
        fail(f"unknown ship step: {step!r}", valid=SHIP_CHAIN)
    return SHIP_CHAIN.index(norm)


def next_step_after(step: str | None) -> str | None:
    if not step:
        return SHIP_CHAIN[0]
    idx = chain_index(step)
    if idx + 1 >= len(SHIP_CHAIN):
        return None
    return SHIP_CHAIN[idx + 1]


def resolve_steps_path(root: Path, phase: str, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    run_dir = os.environ.get("SW_RUN_DIR", "").strip()
    if run_dir:
        return Path(run_dir) / "ship-steps.json"
    return root / ".cursor" / "sw-deliver-runs" / phase / "ship-steps.json"


def load_steps(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = read_json(path)
        return data if isinstance(data, dict) else {}
    except StateCorruptError as exc:
        fail(f"corrupt ship-steps state: {exc}", exit_code=20)


def save_steps(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc["updatedAt"] = utc_now()
    write_json(path, doc)
    os.chmod(path, 0o600)


def cmd_init(root: Path, args: list[str]) -> None:
    phase = _parse_kv(args, "--phase")
    if not phase:
        fail("--phase required")
    out = _parse_kv(args, "--out")
    path = resolve_steps_path(root, phase, out)
    head = _parse_kv(args, "--head") or _git_head(root)
    doc = {
        "phase": phase,
        "currentStep": SHIP_CHAIN[0],
        "lastCompletedStep": None,
        "stepAttempts": {},
        "headAtStart": head,
        "chain": SHIP_CHAIN,
    }
    save_steps(path, doc)
    emit({"verdict": "pass", "action": "ship-steps-init", "path": str(path), "state": doc})


def cmd_get(root: Path, args: list[str]) -> None:
    phase = _parse_kv(args, "--phase") or os.environ.get("SW_PHASE_SLUG", "unknown")
    path = resolve_steps_path(root, phase, _parse_kv(args, "--out"))
    doc = load_steps(path)
    emit(
        {
            "verdict": "pass",
            "present": bool(doc),
            "path": str(path),
            "state": doc or None,
        }
    )


def cmd_attempt(root: Path, args: list[str]) -> None:
    step = _parse_kv(args, "--step")
    if not step:
        fail("--step required")
    norm = normalize_step(step)
    phase = _parse_kv(args, "--phase") or os.environ.get("SW_PHASE_SLUG", "unknown")
    path = resolve_steps_path(root, phase, _parse_kv(args, "--out"))
    doc = load_steps(path)
    if not doc:
        cmd_init(root, ["--phase", phase] + (["--out", str(path)] if _parse_kv(args, "--out") else []))
        doc = load_steps(path)
    attempts = doc.setdefault("stepAttempts", {})
    if not isinstance(attempts, dict):
        attempts = {}
        doc["stepAttempts"] = attempts
    attempts[norm] = int(attempts.get(norm, 0)) + 1
    doc["currentStep"] = norm
    save_steps(path, doc)
    emit({"verdict": "pass", "action": "ship-steps-attempt", "step": norm, "attempts": attempts[norm]})


def cmd_advance(root: Path, args: list[str]) -> None:
    step = _parse_kv(args, "--step")
    if not step:
        fail("--step required")
    norm = normalize_step(step)
    phase = _parse_kv(args, "--phase") or os.environ.get("SW_PHASE_SLUG", "unknown")
    path = resolve_steps_path(root, phase, _parse_kv(args, "--out"))
    doc = load_steps(path)
    if not doc:
        fail("ship-steps missing; run init first", path=str(path))
    doc["lastCompletedStep"] = norm
    nxt = next_step_after(norm)
    doc["currentStep"] = nxt
    save_steps(path, doc)
    emit(
        {
            "verdict": "pass",
            "action": "ship-steps-advance",
            "completed": norm,
            "nextStep": nxt,
        }
    )


def cmd_resolve_resume(root: Path, args: list[str]) -> None:
    explicit_from = _parse_kv(args, "--from")
    phase = _parse_kv(args, "--phase") or os.environ.get("SW_PHASE_SLUG", "unknown")
    path = resolve_steps_path(root, phase, _parse_kv(args, "--out"))
    doc = load_steps(path)

    source = "chain-start"
    next_step: str | None = SHIP_CHAIN[0]

    if explicit_from:
        norm = normalize_step(explicit_from)
        chain_index(norm)
        next_step = norm
        source = "cli-from"
    elif doc.get("currentStep"):
        next_step = normalize_step(str(doc["currentStep"]))
        source = "persisted-current"
    elif doc.get("lastCompletedStep"):
        next_step = next_step_after(str(doc["lastCompletedStep"]))
        source = "persisted-after-last"
    else:
        last_cmd = _parse_kv(args, "--last-command")
        if last_cmd:
            mapped = normalize_step(last_cmd)
            if mapped in SHIP_CHAIN:
                idx = SHIP_CHAIN.index(mapped)
                next_step = SHIP_CHAIN[idx + 1] if idx + 1 < len(SHIP_CHAIN) else None
                source = "last-command"

    emit(
        {
            "verdict": "pass",
            "action": "resolve-resume",
            "nextStep": next_step,
            "source": source,
            "path": str(path),
            "state": doc or None,
        }
    )


def cmd_sync_state(root: Path, args: list[str]) -> None:
    """Merge ship-steps into shipwright.json phaseShip (called from shipwright-state.sh)."""
    phase = _parse_kv(args, "--phase") or os.environ.get("SW_PHASE_SLUG", "unknown")
    path = resolve_steps_path(root, phase, _parse_kv(args, "--out"))
    doc = load_steps(path)
    if not doc:
        emit({"verdict": "pass", "action": "sync-state", "note": "no ship-steps file"})
    phase_ship = {
        "currentStep": doc.get("currentStep"),
        "lastCompletedStep": doc.get("lastCompletedStep"),
        "stepAttempts": doc.get("stepAttempts") or {},
        "phase": doc.get("phase") or phase,
        "stepsPath": str(path),
        "updatedAt": doc.get("updatedAt"),
    }
    emit({"verdict": "pass", "action": "sync-state", "phaseShip": phase_ship})


def _parse_kv(args: list[str], flag: str) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else None
    return None


def _git_head(root: Path) -> str | None:
    import subprocess

    try:
        return (
            subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True)
            .strip()
            or None
        )
    except subprocess.CalledProcessError:
        return None


def main() -> None:
    if len(sys.argv) < 3:
        fail(
            "usage: ship_phase_steps.py <root> <init|get|attempt|advance|resolve-resume|sync-state> [args...]"
        )
    root = Path(sys.argv[1])
    cmd = sys.argv[2]
    args = sys.argv[3:]

    handlers = {
        "init": cmd_init,
        "get": cmd_get,
        "attempt": cmd_attempt,
        "advance": cmd_advance,
        "resolve-resume": cmd_resolve_resume,
        "sync-state": cmd_sync_state,
    }
    handler = handlers.get(cmd)
    if not handler:
        fail(f"unknown command: {cmd}")
    handler(root, args)


if __name__ == "__main__":
    main()
