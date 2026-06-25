#!/usr/bin/env python3
"""Pre-merge compounding and completion semantics for /sw-deliver (PRD 007 R17–R21, R31, R53)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cleanup_lib import load_default_branch
from wave_json_io import StateCorruptError, read_json, write_json

# File outputs safe to commit pre-merge (R18). Memory/provider artifacts are never committed (R19).
ALLOWED_PREMERGE_FILE_PREFIXES = (
    "docs/prds/COMPLETION-LOG.md",
    "docs/prds/INDEX.md",
    "CHANGELOG.md",
    "docs/learnings/",
    ".cursor/sw-deliver-state.json",
)

MEMORY_PATH_MARKERS = (
    ".cursor/memory/",
    "recallium",
    "memory-preflight",
)


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


def state_path(root: Path) -> Path:
    return root / ".cursor" / "sw-deliver-state.json"


def load_state(root: Path) -> dict[str, Any]:
    path = state_path(root)
    try:
        return read_json(path)
    except StateCorruptError as exc:
        fail(f"corrupt durable state: {exc}", exit_code=20, cause="state:corrupt")


def save_state(root: Path, state: dict[str, Any]) -> None:
    state["updatedAt"] = utc_now()
    write_json(state_path(root), state)


def git_top(root: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("not a git repository")
    return Path(proc.stdout.strip())


def current_branch(root: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), "branch", "--show-current"],
        text=True,
        capture_output=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def target_merge_detected(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    target = (state.get("target") or {}).get("branch")
    if not target:
        return {"merged": False, "reason": "no-target-branch"}
    top = git_top(root)
    default = load_default_branch(top)
    target_proc = subprocess.run(
        ["git", "-C", str(top), "rev-parse", target],
        text=True,
        capture_output=True,
    )
    default_proc = subprocess.run(
        ["git", "-C", str(top), "rev-parse", default],
        text=True,
        capture_output=True,
    )
    target_sha = target_proc.stdout.strip() if target_proc.returncode == 0 else ""
    default_sha = default_proc.stdout.strip() if default_proc.returncode == 0 else ""
    if not target_sha or not default_sha:
        return {
            "merged": False,
            "status": "indeterminate",
            "detail": "missing-branch-ref",
            "target": target,
            "default": default,
        }
    anc = subprocess.run(
        ["git", "-C", str(top), "merge-base", "--is-ancestor", target_sha, default_sha],
        capture_output=True,
    )
    if anc.returncode == 0:
        return {
            "merged": True,
            "status": "merged",
            "detail": "ancestor-of-default",
            "target": target,
            "default": default,
        }
    cherry = subprocess.run(
        ["git", "-C", str(top), "cherry", default, target],
        text=True,
        capture_output=True,
    )
    plus = [ln for ln in cherry.stdout.splitlines() if ln.startswith("+")]
    if cherry.returncode == 0 and not plus and cherry.stdout.strip():
        return {
            "merged": True,
            "status": "merged",
            "detail": "squash-cherry",
            "target": target,
            "default": default,
        }
    return {
        "merged": False,
        "status": "unmerged",
        "detail": "not-on-default",
        "target": target,
        "default": default,
    }


def is_allowed_premerge_path(path: str) -> bool:
    if any(marker in path for marker in MEMORY_PATH_MARKERS):
        return False
    return any(path == p or path.startswith(p) for p in ALLOWED_PREMERGE_FILE_PREFIXES)


def changed_files(root: Path, base: str = "HEAD") -> list[str]:
    top = git_top(root)
    files: list[str] = []
    for cmd in (
        ["git", "-C", str(top), "diff", "--name-only", base],
        ["git", "-C", str(top), "diff", "--cached", "--name-only"],
    ):
        proc = subprocess.run(cmd, text=True, capture_output=True)
        if proc.returncode == 0:
            files.extend(ln.strip() for ln in proc.stdout.splitlines() if ln.strip())
    return sorted(set(files))


def cmd_compound_premerge_env(root: Path, _args: list[str]) -> None:
    state = load_state(root) if state_path(root).is_file() else {}
    target = (state.get("target") or {}).get("branch", "<type>/<slug>")
    emit(
        {
            "verdict": "pass",
            "action": "compound-ship-premerge-env",
            "invoke": "/sw-compound-ship --pre-merge",
            "targetBranch": target,
            "fileOutputsCommit": True,
            "memoryCommit": False,
            "reconcileFlags": ["--require-merge"],
            "recordCommand": "bash scripts/wave.sh compound-ship record-premerge --prd <n> --phase <name>",
            "guardrails": {
                "ruleClassPromotion": "human-gated-only",
                "memoryProviderUnreachable": "fail-closed",
            },
        }
    )


def cmd_compound_record_premerge(root: Path, args: list[str]) -> None:
    prd = parse_kv(args, "--prd")
    phase = parse_kv(args, "--phase") or "deliver"
    notes = parse_kv(args, "--notes") or "pre-merge compounding complete"
    if not prd:
        fail("--prd required (e.g. 007)")
    state = load_state(root)
    now = utc_now()
    state["compoundShip"] = {
        "premergeDone": True,
        "mode": "pre-merge",
        "at": now,
        "prd": prd,
        "phase": phase,
        "ruleClassPromotion": "human-gated",
    }
    state["completion"] = {
        "status": "completed-pending-merge",
        "at": now,
        "prd": prd,
        "phase": phase,
        "notes": notes,
    }
    save_state(root, state)
    if not has_flag(args, "--skip-append-log"):
        script = root / "scripts" / "reconcile-status.sh"
        subprocess.run(
            ["bash", str(script), "append-log", prd, phase, notes],
            cwd=str(root),
            check=False,
        )
    emit(
        {
            "verdict": "pass",
            "action": "compound-ship-record-premerge",
            "completion": state["completion"],
            "compoundShip": state["compoundShip"],
        }
    )


def cmd_compound_check_file_outputs(root: Path, args: list[str]) -> None:
    """Verify working tree / last commit touches only allowed pre-merge file paths."""
    base = parse_kv(args, "--base") or "HEAD"
    top = git_top(root)
    files = changed_files(top, base)
    if not files and base == "HEAD":
        files = changed_files(top, "HEAD~1..HEAD")
    disallowed = [f for f in files if not is_allowed_premerge_path(f)]
    memory_like = [f for f in files if any(m in f for m in MEMORY_PATH_MARKERS)]
    if disallowed or memory_like:
        emit(
            {
                "verdict": "fail",
                "error": "pre-merge file outputs include disallowed paths",
                "disallowed": disallowed,
                "memoryLike": memory_like,
                "allowedPrefixes": list(ALLOWED_PREMERGE_FILE_PREFIXES),
            },
            exit_code=1,
        )
    emit(
        {
            "verdict": "pass",
            "action": "compound-ship-check-file-outputs",
            "files": files,
            "memoryCommitted": False,
        }
    )


def cmd_completion_check_merge(root: Path, _args: list[str]) -> None:
    state = load_state(root) if state_path(root).is_file() else {}
    info = target_merge_detected(root, state)
    emit({"verdict": "pass", "action": "completion-check-merge", **info})


def cmd_completion_finalize_if_merged(root: Path, args: list[str]) -> None:
    state = load_state(root)
    completion = state.get("completion") or {}
    if completion.get("status") != "completed-pending-merge":
        fail("completion not in completed-pending-merge state")
    info = target_merge_detected(root, state)
    if not info["merged"]:
        fail(
            "target branch not merged — cannot finalize completion",
            exit_code=10,
            halt="wait",
            **info,
        )
    if not has_flag(args, "--skip-reconcile"):
        script = root / "scripts" / "reconcile-status.sh"
        subprocess.run(
            ["bash", str(script), "reconcile"],
            cwd=str(root),
            check=False,
        )
    state["completion"]["status"] = "merged-complete"
    state["completion"]["mergedAt"] = utc_now()
    state["completion"]["mergeDetail"] = info.get("detail")
    state["verdict"] = "complete"
    save_state(root, state)
    emit(
        {
            "verdict": "pass",
            "action": "completion-finalize",
            "cleanupSuggestion": "Run `/sw-cleanup` to prune merged branches and stale worktrees.",
            "completion": state["completion"],
        }
    )


def cmd_completion_status(root: Path, _args: list[str]) -> None:
    state = load_state(root) if state_path(root).is_file() else {}
    completion = state.get("completion") or {}
    compound = state.get("compoundShip") or {}
    merge_info = target_merge_detected(root, state) if state else {"merged": False}
    terminal_complete = (
        completion.get("status") == "merged-complete"
        or (state.get("verdict") == "complete" and merge_info.get("merged"))
    )
    emit(
        {
            "verdict": "pass",
            "action": "completion-status",
            "completion": completion or None,
            "compoundShip": compound or None,
            "mergeDetected": merge_info.get("merged"),
            "reportsComplete": terminal_complete,
            "cleanupSuggestion": (
                "Run `/sw-cleanup` to prune merged branches and stale worktrees."
                if merge_info.get("merged")
                else None
            ),
        }
    )


def main() -> None:
    if len(sys.argv) < 3:
        fail(
            "usage: wave_compound.py <root> <compound-ship|completion> <subcommand> [args...]"
        )
    root = Path(sys.argv[1])
    domain = sys.argv[2]
    args = sys.argv[3:]

    if domain == "compound-ship":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub in ("premerge-env", "env"):
            cmd_compound_premerge_env(root, rest)
        elif sub in ("record-premerge", "record"):
            cmd_compound_record_premerge(root, rest)
        elif sub in ("check-file-outputs", "check-files"):
            cmd_compound_check_file_outputs(root, rest)
        else:
            fail("compound-ship subcommand: premerge-env|record-premerge|check-file-outputs")
    elif domain == "completion":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "check-merge":
            cmd_completion_check_merge(root, rest)
        elif sub == "finalize-if-merged":
            cmd_completion_finalize_if_merged(root, rest)
        elif sub == "status":
            cmd_completion_status(root, rest)
        else:
            fail("completion subcommand: check-merge|finalize-if-merged|status")
    else:
        fail(f"unknown domain: {domain}")


if __name__ == "__main__":
    main()
