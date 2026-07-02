#!/usr/bin/env python3
"""Fail-closed in-flight cwd guard for work-performing surfaces (PRD 049 R3/R7)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main

INDEX_STALE_SECONDS = 300
REMEDIATION = (
    "Refuse work-performing commands from the primary checkout on defaultBaseBranch during an in-flight "
    "deliver run. Use the orchestrator worktree (`.sw-worktrees/<slug>-orchestrator`) or wait until the "
    "run reaches a terminal verdict."
)


def canonical_repo_root(start: Path | None = None) -> Path:
    start = start or Path.cwd()
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--git-common-dir"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ValueError("not a git repository")
    common = Path(proc.stdout.strip())
    if not common.is_absolute():
        common = (Path(start) / common).resolve()
    return common.parent.resolve()


def git_toplevel(start: Path | None = None) -> Path:
    start = start or Path.cwd()
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ValueError("not a git repository")
    return Path(proc.stdout.strip()).resolve()


def primary_worktree_path(repo_root: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return repo_root.resolve()
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            return Path(line.split(" ", 1)[1].strip()).resolve()
    return repo_root.resolve()


def current_branch(cwd: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--abbrev-ref", "HEAD"],
        text=True,
        capture_output=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def read_config(repo_root: Path) -> dict[str, Any]:
    import reconcile_lib as rl

    return rl.read_config(repo_root)


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _index_is_stale(index: dict[str, Any]) -> bool:
    updated = index.get("updatedAt")
    if not isinstance(updated, str):
        return True
    dt = _parse_ts(updated)
    if not dt:
        return True
    age = (datetime.now(timezone.utc) - dt).total_seconds()
    return age > INDEX_STALE_SECONDS


def _read_index(repo_root: Path) -> tuple[dict[str, Any] | None, str | None]:
    index_path = repo_root / ".cursor" / "sw-deliver-runs" / "index.json"
    if not index_path.is_file():
        return None, None
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "corrupt or unreadable deliver runs index"
    if not isinstance(data, dict):
        return None, "corrupt or unreadable deliver runs index"
    return data, None


def in_flight_runs(repo_root: Path) -> tuple[list[dict[str, Any]], str | None]:
    from wave_state import enumerate_scoped_runs

    index, corrupt = _read_index(repo_root)
    if corrupt:
        return [], corrupt

    use_live_scan = index is None or _index_is_stale(index)
    if use_live_scan:
        runs = enumerate_scoped_runs(repo_root)
    else:
        runs = index.get("runs") if isinstance(index.get("runs"), list) else []
        if not runs:
            runs = enumerate_scoped_runs(repo_root)

    running = [r for r in runs if r.get("verdict") == "running"]
    return running, None


def is_primary_default_branch(cwd: Path | None = None) -> tuple[bool, Path, str, str]:
    cwd = (cwd or Path.cwd()).resolve()
    top = canonical_repo_root(cwd)
    primary = primary_worktree_path(top)
    branch = current_branch(cwd)
    base = str(read_config(top).get("defaultBaseBranch") or "main")
    on_primary = cwd == primary or str(cwd).startswith(str(primary) + "/")
    guarded = on_primary and branch == base
    return guarded, top, branch, base


def check(
    *,
    cwd: Path | None = None,
    allow_default_branch: bool = False,
) -> dict[str, Any]:
    guarded, top, branch, base = is_primary_default_branch(cwd)
    if not guarded:
        return {
            "verdict": "pass",
            "action": "deliver-cwd-guard",
            "guarded": False,
            "gitToplevel": str(top),
            "branch": branch,
        }

    if allow_default_branch:
        print(
            json.dumps(
                {
                    "verdict": "warn",
                    "action": "deliver-cwd-guard",
                    "note": "--allow-default-branch bypass used (CI/fixture only)",
                    "branch": branch,
                }
            ),
            file=sys.stderr,
        )
        return {
            "verdict": "pass",
            "action": "deliver-cwd-guard",
            "guarded": True,
            "bypass": True,
            "gitToplevel": str(top),
            "branch": branch,
        }

    running, corrupt = in_flight_runs(canonical_repo_root(cwd))
    if corrupt:
        return {
            "verdict": "fail",
            "action": "deliver-cwd-guard",
            "error": corrupt,
            "remediation": REMEDIATION,
            "gitToplevel": str(top),
            "branch": branch,
            "failClosed": True,
        }

    if running:
        return {
            "verdict": "fail",
            "action": "deliver-cwd-guard",
            "error": "in-flight deliver run detected on primary checkout",
            "remediation": REMEDIATION,
            "gitToplevel": str(top),
            "branch": branch,
            "defaultBaseBranch": base,
            "inFlightRuns": running,
        }

    return {
        "verdict": "pass",
        "action": "deliver-cwd-guard",
        "guarded": True,
        "gitToplevel": str(top),
        "branch": branch,
    }


def enforce(
    *,
    cwd: Path | None = None,
    allow_default_branch: bool = False,
    exit_code: int = 20,
) -> dict[str, Any]:
    result = check(cwd=cwd, allow_default_branch=allow_default_branch)
    if result.get("verdict") == "fail":
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(exit_code)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deliver_cwd_guard.py")
    parser.add_argument(
        "--allow-default-branch",
        action="store_true",
        help="CI/fixture-only bypass; logs use to stderr",
    )
    parser.add_argument("--cwd", default="", help="Checkout directory to evaluate (default: process cwd)")
    ns = parser.parse_args(argv)
    cwd = Path(ns.cwd).resolve() if ns.cwd else None
    result = check(cwd=cwd, allow_default_branch=ns.allow_default_branch)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("verdict") == "pass" else 20


if __name__ == "__main__":
    run_module_main(main)
