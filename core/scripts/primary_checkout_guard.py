#!/usr/bin/env python3
"""Shared primary-checkout guard for concurrent deliver/doc/amend sessions (PRD 050 R1/R2)."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main

PRIMARY_LOCK = "primary-checkout.lock"
LOCK_STALE_SECONDS = 300


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


def worktree_path_for_branch(repo_root: Path, branch: str) -> Path | None:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    current_path: str | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = line.split(" ", 1)[1].strip()
        elif line.startswith("branch ") and current_path:
            ref = line.split(" ", 1)[1].strip()
            if ref == f"refs/heads/{branch}":
                return Path(current_path).resolve()
    return None


def branch_exists(repo_root: Path, branch: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "show-ref", "--verify", f"refs/heads/{branch}"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return True
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "show-ref", "--verify", f"refs/remotes/origin/{branch}"],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def lock_path(repo_root: Path) -> Path:
    return repo_root / ".cursor" / "sw-deliver-runs" / PRIMARY_LOCK


def acquire_primary_lock(repo_root: Path, *, nonblock: bool = True) -> dict[str, Any]:
    """Advisory lock before mutating primary checkout HEAD (PRD 050 TR3)."""
    path = lock_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    payload = json.dumps({"pid": os.getpid(), "at": time.time()})
    try:
        fd = os.open(str(path), flags)
        os.write(fd, payload.encode())
        os.close(fd)
        return {"verdict": "pass", "action": "primary-lock-acquire", "path": str(path)}
    except FileExistsError:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            age = time.time() - float(data.get("at", 0))
            if age > LOCK_STALE_SECONDS:
                path.unlink(missing_ok=True)
                return acquire_primary_lock(repo_root, nonblock=nonblock)
        except (OSError, json.JSONDecodeError, ValueError):
            pass
        return {
            "verdict": "fail",
            "action": "primary-lock-acquire",
            "error": "primary checkout lock held by concurrent session",
            "remediation": (
                "Wait for the other session to finish, or remove stale lock at "
                f"{path} if no session is active"
            ),
            "path": str(path),
        }


def release_primary_lock(repo_root: Path) -> None:
    lock_path(repo_root).unlink(missing_ok=True)


def guard(resolved_root: Path, artifact_branch: str) -> dict[str, Any]:
    """Fail closed when resolved_root is primary checkout and a dedicated worktree exists for artifact_branch."""
    resolved_root = resolved_root.resolve()
    repo_root = canonical_repo_root(resolved_root)
    primary = primary_worktree_path(repo_root)
    on_primary = resolved_root == primary

    if not on_primary:
        return {
            "verdict": "pass",
            "action": "primary-checkout-guard",
            "onPrimary": False,
            "resolvedRoot": str(resolved_root),
            "primaryCheckout": str(primary),
            "artifactBranch": artifact_branch,
        }

    dedicated = worktree_path_for_branch(repo_root, artifact_branch)
    if dedicated and dedicated != primary:
        return {
            "verdict": "fail",
            "action": "primary-checkout-guard",
            "error": (
                f"refused: cwd resolves to primary checkout while dedicated worktree exists "
                f"for {artifact_branch!r}"
            ),
            "remediation": (
                f"cd {dedicated}  # or use move_agent_to_root to align IDE workspace"
            ),
            "onPrimary": True,
            "resolvedRoot": str(resolved_root),
            "primaryCheckout": str(primary),
            "dedicatedWorktree": str(dedicated),
            "artifactBranch": artifact_branch,
            "halt": "primary-checkout-guard",
        }

    if branch_exists(repo_root, artifact_branch):
        return {
            "verdict": "fail",
            "action": "primary-checkout-guard",
            "error": (
                f"refused: cwd resolves to primary checkout for branch {artifact_branch!r}; "
                "provision a worktree first"
            ),
            "remediation": (
                f"python3 scripts/worktree.py provision <name> --base {artifact_branch}"
            ),
            "onPrimary": True,
            "resolvedRoot": str(resolved_root),
            "primaryCheckout": str(primary),
            "artifactBranch": artifact_branch,
            "halt": "primary-checkout-guard",
        }

    return {
        "verdict": "pass",
        "action": "primary-checkout-guard",
        "onPrimary": True,
        "resolvedRoot": str(resolved_root),
        "primaryCheckout": str(primary),
        "artifactBranch": artifact_branch,
        "note": "no dedicated worktree yet; branch not created",
    }


def enforce_guard(resolved_root: Path, artifact_branch: str, *, exit_code: int = 20) -> dict[str, Any]:
    result = guard(resolved_root, artifact_branch)
    if result.get("verdict") == "fail":
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(exit_code)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="primary_checkout_guard.py")
    sub = parser.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("guard", help="Evaluate primary-checkout guard")
    g.add_argument("--root", default="", help="Resolved root (default: cwd)")
    g.add_argument("--branch", required=True, help="Artifact branch")

    la = sub.add_parser("lock-acquire", help="Acquire primary-checkout advisory lock")
    la.add_argument("--root", default="")

    lr = sub.add_parser("lock-release", help="Release primary-checkout advisory lock")
    lr.add_argument("--root", default="")

    ns = parser.parse_args(argv)
    root = Path(ns.root).resolve() if ns.root else Path.cwd().resolve()
    repo_root = canonical_repo_root(root)

    if ns.cmd == "guard":
        result = guard(root, ns.branch)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("verdict") == "pass" else 20

    if ns.cmd == "lock-acquire":
        result = acquire_primary_lock(repo_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("verdict") == "pass" else 20

    release_primary_lock(repo_root)
    print(json.dumps({"verdict": "pass", "action": "primary-lock-release"}, indent=2))
    return 0


if __name__ == "__main__":
    run_module_main(main)
