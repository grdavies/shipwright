#!/usr/bin/env python3
"""Fail-closed guard refusing INDEX/living-doc commits on defaultBaseBranch (PRD 055 R6/R9)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main

REMEDIATION = (
    "Refuse INDEX/living-doc commits on defaultBaseBranch. Use an orchestrator or feature worktree "
    "(e.g. `.sw-worktrees/<slug>-orchestrator`) for living-docs reconcile and inflight INDEX writes."
)


def read_default_base_branch(root: Path) -> str:
    from reconcile_lib import read_config

    cfg = read_config(root)
    return str(cfg.get("defaultBaseBranch") or "main")


def current_branch(worktree: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "--abbrev-ref", "HEAD"],
        text=True,
        capture_output=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def refuse_default_branch(branch: str, default: str) -> None:
    if branch == default:
        raise ValueError(f"refused: operation targets protected default branch {default!r}")


def refuse_default_branch_commit(
    root: Path,
    *,
    worktree: Path | None = None,
    allow_default: bool = False,
) -> None:
    if allow_default:
        return
    wt = worktree or root
    refuse_default_branch(current_branch(wt), read_default_base_branch(root))


def check(
    root: Path,
    *,
    worktree: Path | None = None,
    allow_default: bool = False,
) -> dict[str, Any]:
    wt = worktree or root
    branch = current_branch(wt)
    base = read_default_base_branch(root)
    if not allow_default and branch == base:
        return {
            "verdict": "fail",
            "action": "default-branch-commit-guard",
            "error": f"refused: operation targets protected default branch {base!r}",
            "branch": branch,
            "defaultBaseBranch": base,
            "remediation": REMEDIATION,
        }
    return {
        "verdict": "pass",
        "action": "default-branch-commit-guard",
        "branch": branch,
        "defaultBaseBranch": base,
        "worktree": str(wt),
    }


def enforce(
    root: Path,
    *,
    worktree: Path | None = None,
    allow_default: bool = False,
    exit_code: int = 20,
) -> dict[str, Any]:
    result = check(root, worktree=worktree, allow_default=allow_default)
    if result.get("verdict") == "fail":
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(exit_code)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="default_branch_commit_guard.py")
    parser.add_argument("repo_root", nargs="?", default=".")
    parser.add_argument("--worktree", default="", help="Checkout to evaluate (default: repo root)")
    parser.add_argument(
        "--allow-default-branch",
        action="store_true",
        help="CI/fixture-only bypass",
    )
    ns = parser.parse_args(argv)
    root = Path(ns.repo_root).resolve()
    worktree = Path(ns.worktree).resolve() if ns.worktree else None
    result = check(root, worktree=worktree, allow_default=ns.allow_default_branch)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("verdict") == "pass" else 20


if __name__ == "__main__":
    run_module_main(main)
