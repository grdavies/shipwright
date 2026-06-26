#!/usr/bin/env python3
"""Living-doc reconciliation for /sw-deliver (R47–R51): INDEX, COMPLETION-LOG, GAP-BACKLOG."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

VALID_INDEX_STATUSES = frozenset({"not-started", "in-progress", "complete"})

LIVING_PATHS = (
    "docs/prds/INDEX.md",
    "docs/prds/COMPLETION-LOG.md",
    "docs/prds/GAP-BACKLOG.md",
)


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


def load_state(root: Path) -> dict[str, Any]:
    from wave_state import resolve_state_path

    path = resolve_state_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def load_plan(root: Path) -> dict[str, Any]:
    path = root / ".cursor" / "sw-deliver-plan.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def prd_number_from_state(state: dict[str, Any], plan: dict[str, Any]) -> str | None:
    raw = state.get("prd_number") or plan.get("prd_number")
    if raw is None:
        return None
    return str(raw).zfill(3)


def derive_index_status(state: dict[str, Any], merged_to_main: bool) -> str:
    phases = state.get("phases") or {}
    if not phases:
        return "not-started"
    statuses = [str((meta or {}).get("status") or "pending") for meta in phases.values()]
    if merged_to_main:
        return "complete"
    if any(s not in ("pending",) for s in statuses):
        return "in-progress"
    return "not-started"


def target_merge_detected(root: Path, state: dict[str, Any]) -> bool:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "wave_compound.py"), str(root), "completion", "check-merge"],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return False
    try:
        data = json.loads(proc.stdout)
        return bool(data.get("merged"))
    except json.JSONDecodeError:
        return False


def resolve_worktree(root: Path, args: list[str]) -> Path:
    wt = parse_kv(args, "--worktree")
    if wt:
        return Path(wt).resolve()
    orch = parse_kv(args, "--orchestrator-worktree")
    if orch:
        return Path(orch).resolve()
    return root.resolve()


def run_reconcile_script(root: Path, *cmd: str) -> dict[str, Any]:
    script = SCRIPT_DIR / "reconcile-status.sh"
    proc = subprocess.run(
        ["bash", str(script), *cmd],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    out = proc.stdout.strip()
    try:
        data = json.loads(out) if out.startswith("{") else {"raw": out}
    except json.JSONDecodeError:
        data = {"raw": out, "stderr": proc.stderr.strip()}
    if proc.returncode != 0:
        fail(
            data.get("error") or proc.stderr.strip() or "reconcile-status failed",
            exit_code=proc.returncode,
            **{k: v for k, v in data.items() if k != "error"},
        )
    return data


def git_commit_living_docs(worktree: Path, prd: str, dry_run: bool) -> str | None:
    top = worktree
    proc = subprocess.run(
        ["git", "-C", str(top), "status", "--porcelain", "--", *LIVING_PATHS],
        text=True,
        capture_output=True,
    )
    if not proc.stdout.strip():
        return None
    if dry_run:
        return "dry-run"
    subprocess.run(["git", "-C", str(top), "add", *LIVING_PATHS], check=True)
    msg = f"chore: living-doc reconcile for PRD {prd}"
    proc = subprocess.run(
        ["git", "-C", str(top), "commit", "-m", msg],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or proc.stdout.strip() or "living-doc commit failed")
    sha_proc = subprocess.run(
        ["git", "-C", str(top), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    )
    return sha_proc.stdout.strip()


def cmd_reconcile(root: Path, args: list[str]) -> None:
    state = load_state(root)
    plan = load_plan(root)
    prd = prd_number_from_state(state, plan)
    if not prd:
        fail("prd_number missing from deliver state/plan")

    merged_main = target_merge_detected(root, state)
    index_status = derive_index_status(state, merged_main)
    worktree = resolve_worktree(root, args)
    dry_run = has_flag(args, "--dry-run")
    do_commit = has_flag(args, "--commit")

    index_out = run_reconcile_script(
        worktree,
        "set-index-status",
        "--prd",
        prd,
        "--status",
        index_status,
    )

    gap_out: dict[str, Any] | None = None
    if index_status == "complete":
        pr_ref = ""
        terminal = state.get("terminalPr") or {}
        if terminal.get("number"):
            pr_ref = str(terminal["number"])
        gap_out = run_reconcile_script(
            worktree,
            "gap-resolve",
            "--absorbing-prd",
            prd,
            *(["--pr", pr_ref] if pr_ref else []),
        )

    commit_sha = None
    if do_commit and not dry_run:
        commit_sha = git_commit_living_docs(worktree, prd, dry_run=False)

    emit(
        {
            "verdict": "pass",
            "action": "living-docs-reconcile",
            "prd": prd,
            "indexStatus": index_status,
            "mergedToMain": merged_main,
            "index": index_out,
            "gapResolve": gap_out,
            "livingDocsCommit": commit_sha,
            "dryRun": dry_run,
        }
    )


def cmd_append_terminal(root: Path, args: list[str]) -> None:
    """Idempotent COMPLETION-LOG append when all phases are green (R48)."""
    state = load_state(root)
    plan = load_plan(root)
    prd = prd_number_from_state(state, plan)
    if not prd:
        fail("prd_number missing from deliver state/plan")

    phases = state.get("phases") or {}
    if phases and not all(
        (meta or {}).get("status") == "green-merged" for meta in phases.values()
    ):
        fail("not all phases green-merged; skip terminal append", exit_code=10)

    worktree = resolve_worktree(root, args)
    phase = parse_kv(args, "--phase") or "all"
    notes = parse_kv(args, "--notes") or "deliver complete — awaiting terminal merge"
    pr = parse_kv(args, "--pr") or ""
    terminal = state.get("terminalPr") or {}
    if not pr and terminal.get("number"):
        pr = str(terminal["number"])

    top = worktree
    sha_proc = subprocess.run(
        ["git", "-C", str(top), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
    )
    head = sha_proc.stdout.strip() if sha_proc.returncode == 0 else ""

    append_args = [
        "append-log-idempotent",
        "--prd",
        prd,
        "--phase",
        phase,
        "--notes",
        notes,
    ]
    if pr:
        append_args.extend(["--pr", pr])
    if head:
        append_args.extend(["--sha", head])

    out = run_reconcile_script(worktree, *append_args)
    commit_sha = None
    if has_flag(args, "--commit"):
        commit_sha = git_commit_living_docs(worktree, prd, dry_run=False)

    emit(
        {
            "verdict": "pass",
            "action": "living-docs-append-terminal",
            "append": out,
            "livingDocsCommit": commit_sha,
        }
    )


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_living_docs.py <root> <reconcile|append-terminal> [args...]")
    root = Path(sys.argv[1]).resolve()
    cmd = sys.argv[2]
    rest = sys.argv[3:]
    if cmd == "reconcile":
        cmd_reconcile(root, rest)
    elif cmd == "append-terminal":
        cmd_append_terminal(root, rest)
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
