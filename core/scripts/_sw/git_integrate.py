#!/usr/bin/env python3
"""Shared git merge primitive for phase→target and execute integrate paths (PRD 053 R16)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

VALID_VERDICTS = frozenset({"pass", "conflict", "fail"})


def _git_run(
    args: list[str],
    cwd: Path,
    *,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=check,
    )


def list_merge_conflict_paths(target_wt: Path) -> list[str]:
    """Enumerate unmerged paths in the target worktree."""
    proc = _git_run(["diff", "--name-only", "--diff-filter=U"], target_wt, check=False)
    paths = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if paths:
        return paths
    proc = _git_run(["ls-files", "-u"], target_wt, check=False)
    seen: set[str] = set()
    for line in proc.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 4:
            seen.add(parts[3].strip())
    return sorted(seen)


def abort_merge(target_wt: Path) -> None:
    """Abort an in-progress merge when present; no-op when clean."""
    if _git_run(["rev-parse", "-q", "--verify", "MERGE_HEAD"], target_wt, check=False).returncode == 0:
        _git_run(["merge", "--abort"], target_wt, check=False)


def merge_branch_into(
    target_wt: Path,
    source_ref: str,
    *,
    message: str | None = None,
    abort_on_conflict: bool = True,
) -> dict[str, Any]:
    """Merge source_ref into target_wt with --no-ff.

    Returns ``{verdict, conflicts[]}``. On conflict with ``abort_on_conflict``,
    aborts the merge so the target worktree is left clean.
    """
    target_wt = target_wt.resolve()
    if not target_wt.is_dir():
        return {"verdict": "fail", "conflicts": [], "error": f"target worktree missing: {target_wt}"}
    if not source_ref.strip():
        return {"verdict": "fail", "conflicts": [], "error": "source_ref required"}

    merge_args = ["merge", "--no-ff", source_ref]
    if message:
        merge_args.extend(["-m", message])
    proc = _git_run(merge_args, target_wt, check=False)
    if proc.returncode == 0:
        return {"verdict": "pass", "conflicts": []}

    conflicts = list_merge_conflict_paths(target_wt)
    if abort_on_conflict:
        abort_merge(target_wt)
    return {"verdict": "conflict", "conflicts": conflicts, "stderr": proc.stderr.strip()}
