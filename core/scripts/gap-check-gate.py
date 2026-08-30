#!/usr/bin/env python3
"""Durable gap-check gate for deliver merge decisions (PRD 055 R13, R25)."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from phase_status_discovery import (
    discover_phase_status,
    halt_dominant_tiebreak,
    preferred_phase_artifact_path,
    resolve_phase_worktree,
)
from status_integrity import (
    check_status_sha,
    remediation_for_status_cause,
    resolve_write_head,
    write_status_atomic,
)

STATUS_NAME = "gap-check.status.json"
FAST_SKIP_ERROR = "deliver-gap-check-no-fast-skip"
ORCHESTRATOR_ROOT_CAUSE = "gap-check-orchestrator-root-artifact"
STALE_HEAD_CAUSE = "gap-check-stale-head"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_deliver_state(root: Path) -> dict[str, Any]:
    try:
        from wave_state import load_deliver_state

        return load_deliver_state(root)
    except Exception:
        return {}


def resolve_phase_write_head(root: Path, phase_slug: str) -> str | None:
    """Authoritative phase worktree HEAD for gap-check binding (PRD 337 R21)."""
    state = _load_deliver_state(root)
    worktree = resolve_phase_worktree(root, phase_slug, state)
    if worktree is None:
        return None
    return resolve_write_head(worktree) or None


def _expected_head(root: Path, worktree: Path | None = None) -> str | None:
    """Prefer phase worktree HEAD so orch/integration tips do not filter phase stamps."""
    if worktree is not None:
        phase_head = resolve_write_head(worktree)
        if phase_head:
            return phase_head
    head = resolve_write_head(root)
    return head or None


def is_orchestrator_root_artifact(path: Path, root: Path, worktree: Path | None) -> bool:
    """Reject orchestrator-root copies when a registered phase worktree exists (R21)."""
    if worktree is None:
        return False
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
        wt_resolved = worktree.resolve()
    except OSError:
        return False
    if not resolved.is_relative_to(root_resolved):
        return False
    return not resolved.is_relative_to(wt_resolved)


def discover_gap_check_status(
    root: Path, phase_slug: str
) -> tuple[Path | None, dict[str, Any] | None]:
    state = _load_deliver_state(root)
    worktree = resolve_phase_worktree(root, phase_slug, state)
    path, data = discover_phase_status(
        root,
        phase_slug,
        STATUS_NAME,
        worktree=worktree,
        expected_head=_expected_head(root, worktree),
        tiebreak=halt_dominant_tiebreak,
        state=state,
    )
    if path is not None and is_orchestrator_root_artifact(path, root, worktree):
        return None, None
    return path, data


def status_path(root: Path, phase_slug: str) -> Path:
    path, _ = discover_gap_check_status(root, phase_slug)
    if path is not None:
        return path
    return preferred_write_path(root, phase_slug)


def preferred_write_path(root: Path, phase_slug: str) -> Path:
    """Write path prefers registered phase worktree mirror (PRD 337 R21)."""
    state = _load_deliver_state(root)
    worktree = resolve_phase_worktree(root, phase_slug, state)
    if worktree is not None:
        return worktree / ".cursor" / "sw-deliver-runs" / phase_slug / STATUS_NAME
    return preferred_phase_artifact_path(
        root, phase_slug, STATUS_NAME, worktree=worktree, state=state
    )


def read_status(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def write_status(
    path: Path,
    verdict: str,
    *,
    cause: str | None = None,
    head: str | None = None,
    evaluation_provenance: dict[str, Any] | None = None,
    require_evaluation: bool = False,
) -> dict[str, Any]:
    # HEAD stamp mirrors ship-phase-status.py status.json writes (PRD 059 R6).
    if not head:
        head = resolve_write_head(path.parent if path.parent.is_dir() else Path.cwd())
    if verdict == "pass" and require_evaluation and not evaluation_provenance:
        raise ValueError("gap-check pass requires authoritative evaluation provenance")
    doc: dict[str, Any] = {
        "verdict": verdict,
        "binding": True,
        "updatedAt": utc_now(),
    }
    if head:
        doc["head"] = head
    if cause:
        doc["cause"] = cause
    if evaluation_provenance:
        doc["evaluationProvenance"] = evaluation_provenance
    return write_status_atomic(path, doc)


def deliver_gap_check_ok(
    root: Path,
    phase_slug: str,
    *,
    require_status: bool = True,
    auto_repair: bool = False,
) -> tuple[bool, str | None]:
    path, data = discover_gap_check_status(root, phase_slug)
    if data is None:
        if require_status:
            if auto_repair:
                from phase_ship_hygiene import try_auto_repair_gap_check_missing

                repair = try_auto_repair_gap_check_missing(root, phase_slug)
                if repair.get("verdict") == "pass":
                    return True, None
                return False, str(repair.get("cause") or "gap-check-missing")
            return False, "gap-check-missing"
        return True, None
    if data.get("verdict") == "halt" and data.get("binding"):
        return False, str(data.get("cause") or "gap-check:halt")
    if data.get("verdict") != "pass" or not data.get("binding"):
        return False, "gap-check-not-pass"
    from phase_ship_hygiene import is_forged_gap_check_status

    if is_forged_gap_check_status(data):
        return False, "gap-check-forged-pass"
    phase_head = resolve_phase_write_head(root, phase_slug)
    if phase_head:
        ok, cause = check_status_sha(data, phase_head)
        if not ok:
            return False, STALE_HEAD_CAUSE if cause == "phase-status:stale" else "gap-check-missing-head"
        if path is not None and is_orchestrator_root_artifact(path, root, resolve_phase_worktree(root, phase_slug, _load_deliver_state(root))):
            return False, ORCHESTRATOR_ROOT_CAUSE
    return True, None


def gap_check_halt_blocks_merge_ready(root: Path, phase_slug: str) -> bool:
    _, data = discover_gap_check_status(root, phase_slug)
    return bool(data and data.get("verdict") == "halt" and data.get("binding"))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Gap-check durable gate (PRD 055 R13)")
    parser.add_argument("command", choices=["check", "write", "read"])
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--phase-slug", required=True)
    parser.add_argument("--verdict", choices=["pass", "halt"])
    parser.add_argument("--cause", default="")
    parser.add_argument("--head", default="")
    parser.add_argument("--deliver-merge", action="store_true")
    parser.add_argument("--fast", action="store_true")
    args = parser.parse_args(argv)

    if args.deliver_merge and args.fast:
        print(json.dumps({"verdict": "fail", "error": FAST_SKIP_ERROR}))
        return 2

    root = Path(args.root).resolve()
    path, discovered = discover_gap_check_status(root, args.phase_slug)
    if path is None:
        path = preferred_write_path(root, args.phase_slug)

    if args.command == "write":
        if not args.verdict:
            print(json.dumps({"verdict": "fail", "error": "--verdict pass|halt required"}))
            return 2
        phase_head = resolve_phase_write_head(root, args.phase_slug)
        head = phase_head or args.head.strip() or None
        evaluation: dict[str, Any] | None = None
        if args.verdict == "pass":
            from phase_ship_hygiene import discover_authoritative_gap_evaluation

            if not head:
                print(json.dumps({"verdict": "fail", "error": "missing phase HEAD for binding write"}))
                return 2
            evaluation = discover_authoritative_gap_evaluation(root, args.phase_slug, head)
            if evaluation is None:
                evaluation = {
                    "source": "gap-check-write",
                    "evaluationHead": head,
                    "evaluatedAt": utc_now(),
                }
        try:
            doc = write_status(
                path,
                args.verdict,
                cause=args.cause or None,
                head=head,
                evaluation_provenance=evaluation,
                require_evaluation=args.verdict == "pass",
            )
        except ValueError as exc:
            print(json.dumps({"verdict": "fail", "error": str(exc)}))
            return 2
        print(json.dumps({"verdict": "pass", "action": "gap-check-write", "path": str(path), **doc}))
        return 0

    if args.command == "read":
        data = discovered if discovered is not None else read_status(path)
        if data is None:
            print(json.dumps({"verdict": "missing", "path": str(path)}))
            return 2
        print(json.dumps(data))
        return 0

    ok, cause = deliver_gap_check_ok(root, args.phase_slug, require_status=args.deliver_merge)
    if ok:
        print(json.dumps({"verdict": "pass", "action": "gap-check-gate"}))
        return 0
    payload: dict[str, Any] = {"verdict": "fail", "error": cause}
    remediation = remediation_for_status_cause(cause)
    if remediation:
        payload["remediation"] = remediation
    print(json.dumps(payload))
    return 1


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
