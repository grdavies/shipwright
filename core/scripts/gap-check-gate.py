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
    resolve_phase_worktree,
)
from status_integrity import resolve_write_head

STATUS_NAME = "gap-check.status.json"
FAST_SKIP_ERROR = "deliver-gap-check-no-fast-skip"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_deliver_state(root: Path) -> dict[str, Any]:
    try:
        from wave_state import load_deliver_state

        return load_deliver_state(root)
    except Exception:
        return {}


def _expected_head(root: Path) -> str | None:
    head = resolve_write_head(root)
    return head or None


def discover_gap_check_status(
    root: Path, phase_slug: str
) -> tuple[Path | None, dict[str, Any] | None]:
    state = _load_deliver_state(root)
    worktree = resolve_phase_worktree(root, phase_slug, state)
    return discover_phase_status(
        root,
        phase_slug,
        STATUS_NAME,
        worktree=worktree,
        expected_head=_expected_head(root),
        tiebreak=halt_dominant_tiebreak,
    )


def status_path(root: Path, phase_slug: str) -> Path:
    path, _ = discover_gap_check_status(root, phase_slug)
    if path is not None:
        return path
    return root / ".cursor" / "sw-deliver-runs" / phase_slug / STATUS_NAME


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
) -> dict[str, Any]:
  # HEAD stamp mirrors ship-phase-status.py status.json writes (PRD 059 R6).
    if not head:
        head = resolve_write_head(path.parent if path.parent.is_dir() else Path.cwd())
    doc: dict[str, Any] = {
        "verdict": verdict,
        "binding": True,
        "updatedAt": utc_now(),
    }
    if head:
        doc["head"] = head
    if cause:
        doc["cause"] = cause
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def deliver_gap_check_ok(root: Path, phase_slug: str, *, require_status: bool = True) -> tuple[bool, str | None]:
    path, data = discover_gap_check_status(root, phase_slug)
    if data is None:
        if require_status:
            return False, "gap-check-missing"
        return True, None
    if data.get("verdict") == "halt" and data.get("binding"):
        return False, str(data.get("cause") or "gap-check:halt")
    if data.get("verdict") != "pass" or not data.get("binding"):
        return False, "gap-check-not-pass"
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
        path = root / ".cursor" / "sw-deliver-runs" / args.phase_slug / STATUS_NAME

    if args.command == "write":
        if not args.verdict:
            print(json.dumps({"verdict": "fail", "error": "--verdict pass|halt required"}))
            return 2
        head = args.head.strip() or None
        doc = write_status(path, args.verdict, cause=args.cause or None, head=head)
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
    print(json.dumps({"verdict": "fail", "error": cause}))
    return 1


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
